from setuptools import setup, find_packages

setup(
    name='datablox_framework',
    version='1.0',
    author='MPI',
    author_email='',
    url='',
    packages=find_packages(),
    include_package_data=True,
    zip_safe=False,
    entry_points = {
        'console_scripts': [
            ]},
    install_requires=[],
    license='Apache V2.0',
    description='A dataflow language and runtime',
    long_description="description"
    )