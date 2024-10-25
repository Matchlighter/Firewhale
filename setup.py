from setuptools import setup

setup(
    name='firewhale',
    version='0.1',
    description='',
    url='',
    author='Matchlighter',
    author_email='ml@matchlighter.net',
    license='MIT',
    packages=['firewhale'],
    install_requires=[
        'ansibleguy-nftables',
        'docker',
        'pyyaml',
    ],
    entry_points={
        'console_scripts': [
            'firewhale = firewhale:main'
        ]
    }
)
