# coding=utf-8

from functools import total_ordering

from semver import SemVer

from conans.errors import ConanException


@total_ordering
class Version(object):
    _semver = None
    loose = True  # Allow incomplete version strings like '1.2' or '1-dev0'

    def __init__(self, value):
        v = str(value).strip()
        try:
            self._semver = SemVer(v, loose=self.loose)
        except ValueError:
            raise ConanException("Invalid version '{}'".format(value))

    @property
    def major(self):
        return str(self._semver.major)

    @property
    def minor(self):
        return str(self._semver.minor)

    @property
    def patch(self):
        return str(self._semver.patch)

    @property
    def micro_versions(self):
        return str(".".join(map(str, self._semver.micro_versions)))

    @property
    def prerelease(self):
        return str(".".join(map(str, self._semver.prerelease)))

    @property
    def build(self):
        return str(".".join(map(str, self._semver.build)))

    def __eq__(self, other):
        if not isinstance(other, Version):
            other = Version(other)
        return (self._semver.compare(other._semver) or self._compare_micro(other)) == 0

    def __lt__(self, other):
        if not isinstance(other, Version):
            other = Version(other)
        return (self._semver.compare(other._semver) or self._compare_micro(other)) < 0

    def _compare_micro(self, other):
        if self.micro_versions == other.micro_versions:
            return 0
        return -1 if self.micro_versions < other.micro_versions else 1
