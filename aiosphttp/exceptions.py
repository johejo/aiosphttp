from yarl import URL


class BaseDownloaderException(Exception):
    msg_header = None


class InitializationError(BaseDownloaderException):
    msg_header = 'An error occurred during initialization. '

    def __str__(self):
        return self.msg_header


class BaseStatusError(BaseDownloaderException):
    def __init__(self, url, status):
        self.url = URL(url)
        self.status = status
        self.method = None

    def gen_msg(self):
        return 'Response status of {} request sent to [{}:{}] was [{}]'\
            .format(self.method, self.url.host, self.url.port, self.status)


class HeadStatusError(InitializationError, BaseStatusError):
    def __init__(self, *args):
        super().__init__(*args)
        self.method = 'HEAD'

    def __str__(self):
        return self.msg_header + self.gen_msg()


class BaseDownloadError(BaseDownloaderException):
    msg_header = 'An error occurred during download. '

    def __str__(self):
        return self.msg_header


class DownloaderStatusError(BaseStatusError, BaseDownloadError):
    def __init__(self, *args):
        super().__init__(*args)
        self.method = 'GET'

    def __str__(self):
        return self.msg_header + self.gen_msg()


class FileSizeError(InitializationError):
    def __str__(self):
        return self.msg_header + 'File sizes are different on each host.'


class CurrentTimeAcquisitionError(BaseDownloaderException):
    def __str__(self):
        return 'Download has not started.'
