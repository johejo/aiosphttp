import warnings
import time

import aiohttp

from .downloader import Downloader
from .exceptions import DownloaderStatusError


class AsyncDownloader(Downloader):
    def __init__(self, urls, **kwargs):
        super().__init__(urls, **kwargs)

    async def async_generator(self):
        while not self._is_complete():
            self._started = True
            self._begin = time.monotonic()
            for sess_id, _ in enumerate(self._sessions):
                self._check_invalid_block(sess_id)

                try:
                    block_id = self._select_block_id(sess_id)
                except IndexError:
                    break

                headers = self._gen_range_header(block_id)

                try:
                    body = await self._request(sess_id, headers)

                except aiohttp.ClientError:
                    msg = '"aiohttp.ClientError" occurred in ' \
                          'session between [{}].' \
                        .format(self._urls[sess_id].host)
                    warnings.warn(msg)
                    self._block_id_q.appendleft(block_id)
                    break

                except DownloaderStatusError as e:
                    warnings.warn(str(e))
                    self._block_id_q.appendleft(block_id)
                    break

                else:
                    if self._buf[block_id] is None:
                        self._buf[block_id] = body

                b = bytearray()
                i = self._returned

                while i < len(self._buf):
                    if self._buf[i] is None:
                        break
                    else:
                        b += self._buf[i]
                        self._buf[i] = True
                        i += 1
                self._returned = i
                self._logger.debug('Return: bytes={}'.format(len(b)))
                yield bytes(b)

        for sess_id, _ in enumerate(self._sessions):
            await self._close(sess_id)
