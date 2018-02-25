import asyncio
import time
import threading
from collections import deque
from logging import getLogger, NullHandler

from yarl import URL
import aiohttp

local_logger = getLogger(__name__)
local_logger.addHandler(NullHandler())

REDIRECTS_STATUS = (302, 302, 303, 307, 308)


# Check if the contents of sequence are all the same
def match_all(es):
    """
    :param es: list
    :return: bool
    """
    return all([e == es[0] for e in es[1:]]) if es else False


class AioSphttpError(Exception):
    pass


class HeadResponseError(AioSphttpError):
    pass


class StatusError(AioSphttpError):
    pass


class InitializationError(AioSphttpError, RuntimeError):
    pass


class EnhancedDeque(deque):
    def __init__(self):
        super().__init__()

    def pop_at_any_pos(self, pos):
        value = self[pos]
        del self[pos]
        return value


class Downloader(object):
    def __init__(self, urls, *, split_size=10 ** 6, loop=None,
                 initial_delay_coefficient=10, initial_delay_prediction=True,
                 dynamic_block_num_selection=True, duplicate_request=True,
                 allow_redirects=True, threshold=20, logger=local_logger):

        self._urls = [URL(url) for url in urls]
        self._split_size = split_size
        self._threshold = threshold
        self._dbns = dynamic_block_num_selection
        self._dr = duplicate_request
        self._ar = allow_redirects
        self._logger = logger

        if loop is None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        self._loop = loop

        w = [self._create_session() for _ in self._urls]
        done, _ = self._loop.run_until_complete(asyncio.wait(w))
        self._sessions = [d.result() for d in done]

        length, delays = self._init_request()
        if match_all(length):
            self._length = length[0]
        else:
            self._logger.error('File sizes are different on each host.')
            raise InitializationError

        self._num_req = int(self._length // self._split_size)
        self._reminder = self._length % self._split_size
        if self._reminder:
            self._num_req += 1

        self._block_id_q = EnhancedDeque()
        for i in range(self._num_req):
            self._block_id_q.append(i)

        min_d = min(delays)
        self._delays = [int((d / min_d - 1) * initial_delay_coefficient)
                        if initial_delay_prediction and (d / min_d) > 2 else 0
                        for d in delays]

        self._dup_q = [0 for _ in self._sessions]
        self._buf = [None for _ in range(self._num_req)]
        self._thread_event = threading.Event()
        self._thread_lock = threading.Lock()
        self._async_lock = asyncio.Lock()
        self._dl_thread = threading.Thread(target=self._download)
        self._init = [True for _ in self._sessions]
        self._received = 0
        self._returned = 0
        self._prev = [0 for _ in self._sessions]
        self._started = False
        self._invalid_block_num = 0

        self._send_log = []
        self._recv_log = []
        self._begin = None

        self._logger.debug('Initial raw delays: {}'.format(delays))

    def generator(self):
        if not self._started:
            self.start()

        while not self._is_complete():
            yield self._concat_buf()

    def start(self):
        if not self._started:
            self._started = True
            self._begin = time.monotonic()
            self._dl_thread.start()

    def get_logs(self):
        if not self._is_complete():
            raise RuntimeError('Download has not completed.')
        return self._recv_log, self._send_log

    def _get_current_time(self):
        if not self._started:
            raise RuntimeError('Download has not stated.')
        return time.monotonic() - self._begin

    def _count_invalid_block(self):
        c = 0
        i = self._returned

        while i < len(self._buf):
            if type(self._buf[i]) is bytes:
                c += 1
            i += 1

        return c

    def _concat_buf(self):
        b = bytearray()
        i = self._returned

        while i < len(self._buf):
            if self._buf[i] is None:
                break
            else:
                b += self._buf[i]
                self._buf[i] = True
                i += 1

        with self._thread_lock:
            self._returned = i

        c = self._count_invalid_block()

        with self._thread_lock:
            self._invalid_block_num = c

        if len(b) == 0:
            self._thread_event.clear()
            self._thread_event.wait()
            return self._concat_buf()
        else:
            self._logger.debug('Return: bytes={}'.format(len(b)))
            return bytes(b)

    async def _create_session(self):
        return aiohttp.ClientSession(loop=self._loop)

    async def _close(self, sess_id):
        await self._sessions[sess_id].close()

    async def _head(self, sess_id):
        sess = self._sessions[sess_id]

        while True:
            url = self._urls[sess_id]
            begin = time.monotonic()

            async with sess.head(url.human_repr()) as resp:
                if resp.status == 200:
                    length = int(resp.headers.get(aiohttp.hdrs.CONTENT_LENGTH))
                    delay = time.monotonic() - begin
                    break

                elif resp.status in REDIRECTS_STATUS and self._ar:
                    r_url = URL(resp.headers.get(aiohttp.hdrs.LOCATION) or
                                resp.headers.get(aiohttp.hdrs.URI))
                    if r_url.is_absolute():
                        self._urls[sess_id] = r_url
                    else:
                        self._urls[sess_id] = URL(url).with_path(r_url.path)

                else:
                    self._logger.error('Response status code of '
                                       'HEAD request sent to {} was {}'
                                       .format(url.host, resp.status))
                    raise HeadResponseError
        return length, (sess_id, delay)

    def _init_request(self):
        w = [self._head(sess_id) for sess_id, _ in enumerate(self._sessions)]
        done, _ = self._loop.run_until_complete(asyncio.wait(w))

        r = [d.result() for d in done]
        length = [l for l, _ in r]
        delays = [d for _, d in sorted([t for _, t in r], key=lambda x: x[0])]

        return length, delays

    def _gen_range_header(self, block_id):
        begin = block_id * self._split_size
        if block_id == self._num_req - 1 and self._reminder:
            end = begin + self._reminder - 1
        else:
            end = begin + self._split_size - 1

        return {'Range': 'bytes={}-{}'.format(begin, end)}

    def _select_block_id(self, sess_id):
        if self._dbns:
            d = max(self._delays[sess_id], 0)
            if d == min(self._delays):
                d = 0
        else:
            d = 0

        block_id = self._block_id_q.pop_at_any_pos(d)
        self._logger.debug('Send req: '
                           'sess_id={}, block_id={}, delay={}, received={}, '
                           'returned={}, remain={}, delays={}, dup_q={}'
                           .format(sess_id, block_id, d, self._received,
                                   self._returned, len(self._block_id_q),
                                   self._delays, self._dup_q))
        self._send_log.append((self._get_current_time(), block_id,
                               self._urls[sess_id].host))
        self._dup_q[sess_id] = block_id

        return block_id

    def _check_invalid_block(self, sess_id):
        target = min(self._dup_q)
        if self._dr and self._delays[sess_id] == min(self._delays) \
                and self._invalid_block_num > self._threshold \
                and self._buf[target] is None:
            self._logger.debug('Exceed threshold: '
                               'invalid_block_num={}, target={}'
                               .format(self._invalid_block_num, target))
            self._block_id_q.appendleft(target)

    def _update_delays(self, sess_id):
        n = self._received - self._prev[sess_id]
        self._delays[sess_id] = n - len(self._sessions)
        self._prev[sess_id] = self._received
        self._received += 1

    async def _request(self, sess_id, headers):
        sess = self._sessions[sess_id]
        url = self._urls[sess_id]

        async with sess.get(url.human_repr(), headers=headers) as resp:
            if resp.status != 206:
                self._logger.warning('Response status code of '
                                     'the range request sent to {} was {}.'
                                     .format(url.host, resp.status))
                raise StatusError

            return await resp.read()

    async def _coro(self, sess_id):

        while not self._is_complete():
            self._check_invalid_block(sess_id)

            try:
                block_id = self._select_block_id(sess_id)
            except IndexError:
                break

            headers = self._gen_range_header(block_id)

            try:
                body = await self._request(sess_id, headers)
                if self._buf[block_id] is None:
                    self._buf[block_id] = body

            except aiohttp.ClientError:
                self._logger.warning('"aiohttp.ClientError" occurred '
                                     'in session between {}.'
                                     .format(self._urls[sess_id].host))
                self._block_id_q.appendleft(block_id)
                break

            except StatusError:
                self._block_id_q.appendleft(block_id)
                break

            self._thread_event.set()
            self._logger.debug('Recv res: '
                               'sess_id={}, block_id={}, received={}, '
                               'returned={}, remain={}, '
                               .format(sess_id, block_id, self._received,
                                       self._returned, len(self._block_id_q)))
            self._recv_log.append((self._get_current_time(), block_id,
                                   self._urls[sess_id].host))
            self._update_delays(sess_id)

    def _download(self):
        w = [self._coro(sess_id) for sess_id, _ in enumerate(self._sessions)]
        self._loop.run_until_complete(asyncio.wait(w))

        w = [self._close(sess_id) for sess_id, _ in enumerate(self._sessions)]
        self._loop.run_until_complete(asyncio.wait(w))

    def _is_complete(self):
        if self._returned == self._num_req:
            return True
        else:
            return False
