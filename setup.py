from setuptools import setup, find_packages


def read(fname):
    with open(fname, 'rt', encoding='utf8') as f:
        return f.read()


setup(
    name='aiosphttp',
    version='0.1.0',
    author='Mitsuo Heijo',
    author_email='mitsuo_h@outlook.com',
    description='Split downloader using http-range request and aiohttp',
    long_description=read('README.md'),
    packages=find_packages(),
    license='MIT',
    url='https://github.com/johejo/aiosphttp',
    py_modules=['aiosphttp'],
    keywords=['HTTP', 'http-client', 'multi-http', 'range-request', 'aiohttp'],
    python_requires='>=3.5.3',
    install_requires=read('requirements.txt').split('\n'),
    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Operating System :: MacOS :: MacOS X',
        'Operating System :: Microsoft :: Windows',
        'Operating System :: POSIX',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6',
    ]
)
