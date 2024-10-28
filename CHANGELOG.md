# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project tries to adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.0.3] - 2024-10-19

### Updates
* Fix: Fix support for displays with other than 16 rows. 

### Additions

### Deprecations
* `get_image_data` - parameter `columns` is not used anymore, function gets this information from the image data itself, since having e.g. 12 rows made this information irrelevant to all other calculations. Probably will remove it in next version or something.

### Contributors to this release