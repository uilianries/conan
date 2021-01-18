from conan.tools.cmake.android import CMakeAndroidToolchain
from conan.tools.cmake.ios import CMakeiOSToolchain
from conan.tools.cmake.generic import CMakeGenericToolchain


def CMakeToolchain(conanfile, **kwargs):
    os_ = conanfile.settings.get_safe('os')
    if os_ == 'Android':
        # assert cross_building(conanfile)  # FIXME: Conan v2.0, two-profiles approach by default
        return CMakeAndroidToolchain(conanfile, **kwargs)
    if os_ == 'iOS':
        return CMakeiOSToolchain(conanfile, **kwargs)
    else:
        return CMakeGenericToolchain(conanfile, **kwargs)
