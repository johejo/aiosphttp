# aiosphttp

## Description
Split downloader using http-range request and aiohttp

## Install

```
$ pip install git+https://github.com/johejo/aiosphttp.git
```

## Usgae

```python
from aiosphttp.downloader import Downloader

urls = [
    'http://ftp.jaist.ac.jp/pub/Linux/ubuntu-releases/artful/ubuntu-17.10.1-server-amd64.iso',
    'http://ubuntutym2.u-toyama.ac.jp/ubuntu/artful/ubuntu-17.10.1-server-amd64.iso',
    'http://ftp.tsukuba.wide.ad.jp/Linux/ubuntu-releases/17.10.1/ubuntu-17.10.1-server-amd64.iso',
    'http://mirror.dmmlabs.jp/linux/ubuntu/17.10.1/ubuntu-17.10.1-server-amd64.iso',
    'http://www.ftp.ne.jp/Linux/packages/ubuntu/releases-cd/17.10.1/ubuntu-17.10.1-server-amd64.iso',
    'http://releases.ubuntu.com/artful/ubuntu-17.10.1-server-amd64.iso',
    'http://mirrorservice.org/sites/releases.ubuntu.com/artful/ubuntu-17.10.1-server-amd64.iso',
    'http://ubuntu.ipacct.com/releases/artful/ubuntu-17.10.1-server-amd64.iso',
    'http://mirror.pop-sc.rnp.br/mirror/ubuntu-releases/artful/ubuntu-17.10.1-server-amd64.iso',
    'http://ftp.belnet.be/ubuntu.com/ubuntu/releases/artful/ubuntu-17.10.1-server-amd64.iso',
    'http://mirrors.mit.edu/ubuntu-releases/artful/ubuntu-17.10.1-server-amd64.iso',
]

d = Downloader(urls, split_size=10**6)
gen = d.generator()

for part in gen:
    print(len(part)) # do something with part

```

## License
MIT