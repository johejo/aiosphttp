import asyncio
import time
from collections import deque
from threading import Thread, Event, Lock
from logging import getLogger, NullHandler

from yarl import URL
from aiohttp import ClientSession, ClientError

local_logger = getLogger(__name__)
local_logger.addHandler(NullHandler())


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


class AnyPoppableDeque(deque):
    def __init__(self):
        super().__init__()

    def pop_at_any_pos(self, pos):
        value = self[pos]
        del self[pos]
        return value


class AsyncDownloader(object):
    def __init__(self, urls, *, split_size=10**6, loop=None, init_coef=10,
                 dynamic_block_num_selection=False, dup_req=True,
                 threshold=20, logger=local_logger):

        self._urls = [URL(url) for url in urls]
        self._split_size = split_size
        self._threshold = threshold
        self._dbns = dynamic_block_num_selection
        self._dup_req = dup_req
        self._logger = logger

        if loop is None:
            loop = asyncio.get_event_loop()
        self._loop = loop

        w = [self._establish() for _ in self._urls]
        done, _ = self._loop.run_until_complete(asyncio.wait(w))
        self._sessions = [d.result() for d in done]

        length, delays = self._get_length()
        if match_all(length):
            self._length = length[0]
        else:
            raise RuntimeError

        self._num_req = int(self._length // self._split_size)
        self._reminder = self._length % self._split_size
        if self._reminder:
            self._num_req += 1

        self._block_id_q = AnyPoppableDeque()
        for i in range(self._num_req):
            self._block_id_q.append(i)

        self._dup_q = [None for _ in self._sessions]

        min_d = min(delays)
        self._delays = [int((d / min_d - 1) * init_coef) for d in delays]

        self._buf = [None for _ in range(self._num_req)]
        self._event = Event()
        self._lock = Lock()
        self._dl_thread = Thread(target=self._download)
        self._init = [True for _ in self._sessions]
        self._received = 0
        self._returned = 0
        self._prev = [0 for _ in self._sessions]
        self._started = False
        self._invalid_block_count = 0
        self._logger.debug('Initialized')

    def generator(self):
        if not self._started:
            self.start()

        while not self._is_complete():
            yield self._concat_buf()

    def start(self):
        if not self._started:
            self._dl_thread.start()

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

        with self._lock:
            self._returned = i

        c = 0
        for buf in self._buf:
            if type(buf) is bytes:
                c += 1

        with self._lock:
            self._invalid_block_count = c

        if len(b) == 0:
            self._event.clear()
            self._event.wait()
            return self._concat_buf()
        else:
            self._logger.debug('return: {}bytes'.format(len(b)))
            return bytes(b)

    async def _establish(self):
        return ClientSession(loop=self._loop)

    async def _close(self, sess_id):
        await self._sessions[sess_id].close()

    async def _head(self, sess_id):
        begin = time.monotonic()
        sess = self._sessions[sess_id]
        url = self._urls[sess_id]
        async with sess.head(url.human_repr()) as resp:
            if resp.status != 200:
                raise HeadResponseError('status={}, host={}'
                                        .format(resp.status, url.host))
            finish = time.monotonic()
            return int(resp.headers['Content-Length']), finish - begin

    def _get_length(self):
        w = [self._head(sess_id) for sess_id, _ in enumerate(self._sessions)]
        done, _ = self._loop.run_until_complete(asyncio.wait(w))

        r = [d.result() for d in done]
        length = [l for l, _ in r]
        delays = [d for _, d in r]

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
        self._logger.debug('send req: '
                           'sess_id={}, block_id={}, delay={}, received={}, '
                           'returned={}, remain={}, delays={}'
                           .format(sess_id, block_id, d, self._received,
                                   self._returned, len(self._block_id_q),
                                   self._delays))
        return block_id

    def _check_invalid_block(self):
        if self._invalid_block_count > self._threshold and self._dup_req:
            self._logger.debug('Exceed threshold')
            self._block_id_q.appendleft(min(self._dup_q))

    def _update_delays(self, sess_id):
        n = self._received - self._prev[sess_id]
        self._delays[sess_id] = n - len(self._sessions)
        self._prev[sess_id] = self._received

        with self._lock:
            self._received += 1

    async def _get(self, sess_id):
        sess = self._sessions[sess_id]
        url = self._urls[sess_id]

        while not self._is_complete():
            self._check_invalid_block()

            try:
                block_id = self._select_block_id(sess_id)
                self._dup_q[sess_id] = block_id
            except IndexError:
                break

            headers = self._gen_range_header(block_id)

            try:
                async with sess.get(url.human_repr(),
                                    headers=headers) as resp:
                    if resp.status != 206:
                        raise StatusError('status={}, host={}'
                                          .format(resp.status, url.host))
                    body = await resp.read()
                    if self._buf[block_id] is None:
                        self._buf[block_id] = body

            except ClientError:
                self._logger.debug('ClientError has raised: '
                                   'sess_id={}, host={}'
                                   .format(sess_id, url.host))
                self._block_id_q.appendleft(block_id)
                break

            self._event.set()
            self._logger.debug('recv res: '
                               'sess_id={}, block_id={}, received={}, '
                               'returned={}, remain={}, '
                               .format(sess_id, block_id, self._received,
                                       self._returned, len(self._block_id_q)))
            self._update_delays(sess_id)

    def _download(self):
        w = [self._get(sess_id) for sess_id, _ in enumerate(self._sessions)]
        self._loop.run_until_complete(asyncio.wait(w))

        w = [self._close(sess_id) for sess_id, _ in enumerate(self._sessions)]
        self._loop.run_until_complete(asyncio.wait(w))

    def _is_complete(self):
        if self._returned == self._num_req:
            return True
        else:
            return False
