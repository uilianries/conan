import logging
import os
import textwrap

from jinja2 import Template
from six.moves.configparser import ConfigParser, NoSectionError

from conans.errors import ConanException
from conans.model.env_info import unquote
from conans.paths import DEFAULT_PROFILE_NAME, conan_expand_user, CACERT_FILE
from conans.util.conan_v2_mode import CONAN_V2_MODE_ENVVAR
from conans.util.dates import timedelta_from_text
from conans.util.env_reader import get_env
from conans.util.files import load

_t_default_settings_yml = Template(textwrap.dedent("""
    # Only for cross building, 'os_build/arch_build' is the system that runs Conan
    os_build: [Windows, WindowsStore, Linux, Macos, FreeBSD, SunOS, AIX]
    arch_build: [x86, x86_64, ppc32be, ppc32, ppc64le, ppc64, armv5el, armv5hf, armv6, armv7, armv7hf, armv7s, armv7k, armv8, armv8_32, armv8.3, sparc, sparcv9, mips, mips64, avr, s390, s390x, sh4le, e2k-v2, e2k-v3, e2k-v4, e2k-v5, e2k-v6, e2k-v7]

    # Only for building cross compilation tools, 'os_target/arch_target' is the system for
    # which the tools generate code
    os_target: [Windows, Linux, Macos, Android, iOS, watchOS, tvOS, FreeBSD, SunOS, AIX, Arduino, Neutrino]
    arch_target: [x86, x86_64, ppc32be, ppc32, ppc64le, ppc64, armv5el, armv5hf, armv6, armv7, armv7hf, armv7s, armv7k, armv8, armv8_32, armv8.3, sparc, sparcv9, mips, mips64, avr, s390, s390x, asm.js, wasm, sh4le, e2k-v2, e2k-v3, e2k-v4, e2k-v5, e2k-v6, e2k-v7]

    # Rest of the settings are "host" settings:
    # - For native building/cross building: Where the library/program will run.
    # - For building cross compilation tools: Where the cross compiler will run.
    os:
        Windows:
            subsystem: [None, cygwin, msys, msys2, wsl]
        WindowsStore:
            version: ["8.1", "10.0"]
        WindowsCE:
            platform: ANY
            version: ["5.0", "6.0", "7.0", "8.0"]
        Linux:
        Macos:
            version: [None, "10.6", "10.7", "10.8", "10.9", "10.10", "10.11", "10.12", "10.13", "10.14", "10.15", "11.0"]
            sdk: [None, "macosx"]
            subsystem: [None, "Catalyst"]
        Android:
            api_level: ANY
        iOS:
            version: ["7.0", "7.1", "8.0", "8.1", "8.2", "8.3", "9.0", "9.1", "9.2", "9.3", "10.0", "10.1", "10.2", "10.3", "11.0", "11.1", "11.2", "11.3", "11.4", "12.0", "12.1", "12.2", "12.3", "12.4", "13.0", "13.1", "13.2", "13.3", "13.4", "13.5", "13.6"]
            sdk: [None, "iphoneos", "iphonesimulator"]
        watchOS:
            version: ["4.0", "4.1", "4.2", "4.3", "5.0", "5.1", "5.2", "5.3", "6.0", "6.1"]
            sdk: [None, "watchos", "watchsimulator"]
        tvOS:
            version: ["11.0", "11.1", "11.2", "11.3", "11.4", "12.0", "12.1", "12.2", "12.3", "12.4", "13.0"]
            sdk: [None, "appletvos", "appletvsimulator"]
        FreeBSD:
        SunOS:
        AIX:
        Arduino:
            board: ANY
        Emscripten:
        Neutrino:
            version: ["6.4", "6.5", "6.6", "7.0", "7.1"]
    arch: [x86, x86_64, ppc32be, ppc32, ppc64le, ppc64, armv4, armv4i, armv5el, armv5hf, armv6, armv7, armv7hf, armv7s, armv7k, armv8, armv8_32, armv8.3, sparc, sparcv9, mips, mips64, avr, s390, s390x, asm.js, wasm, sh4le, e2k-v2, e2k-v3, e2k-v4, e2k-v5, e2k-v6, e2k-v7]
    compiler:
        sun-cc:
            version: ["5.10", "5.11", "5.12", "5.13", "5.14", "5.15"]
            threads: [None, posix]
            libcxx: [libCstd, libstdcxx, libstlport, libstdc++]
        gcc: &gcc
            version: ["4.1", "4.4", "4.5", "4.6", "4.7", "4.8", "4.9",
                      "5", "5.1", "5.2", "5.3", "5.4", "5.5",
                      "6", "6.1", "6.2", "6.3", "6.4", "6.5",
                      "7", "7.1", "7.2", "7.3", "7.4", "7.5",
                      "8", "8.1", "8.2", "8.3", "8.4",
                      "9", "9.1", "9.2", "9.3",
                      "10", "10.1"]
            libcxx: [libstdc++, libstdc++11]
            threads: [None, posix, win32] #  Windows MinGW
            exception: [None, dwarf2, sjlj, seh] # Windows MinGW
            cppstd: [None, 98, gnu98, 11, gnu11, 14, gnu14, 17, gnu17, 20, gnu20]
        Visual Studio: &visual_studio
            runtime: [MD, MT, MTd, MDd]
            version: ["8", "9", "10", "11", "12", "14", "15", "16"]
            toolset: [None, v90, v100, v110, v110_xp, v120, v120_xp,
                      v140, v140_xp, v140_clang_c2, LLVM-vs2012, LLVM-vs2012_xp,
                      LLVM-vs2013, LLVM-vs2013_xp, LLVM-vs2014, LLVM-vs2014_xp,
                      LLVM-vs2017, LLVM-vs2017_xp, v141, v141_xp, v141_clang_c2, v142,
                      llvm, ClangCL]
            cppstd: [None, 14, 17, 20]
        msvc:
            version: ["19.0",
                      "19.1", "19.10", "19.11", "19.12", "19.13", "19.14", "19.15", "19.16",
                      "19.2", "19.20", "19.21", "19.22", "19.23", "19.24", "19.25", "19.26", "19.27", "19.28"]
            runtime: [static, dynamic]
            runtime_type: [Debug, Release]
            cppstd: [14, 17, 20]
        clang:
            version: ["3.3", "3.4", "3.5", "3.6", "3.7", "3.8", "3.9", "4.0",
                      "5.0", "6.0", "7.0", "7.1",
                      "8", "9", "10", "11"]
            libcxx: [None, libstdc++, libstdc++11, libc++, c++_shared, c++_static]
            cppstd: [None, 98, gnu98, 11, gnu11, 14, gnu14, 17, gnu17, 20, gnu20]
            runtime: [None, MD, MT, MTd, MDd]
        apple-clang: &apple_clang
            version: ["5.0", "5.1", "6.0", "6.1", "7.0", "7.3", "8.0", "8.1", "9.0", "9.1", "10.0", "11.0", "12.0"]
            libcxx: [libstdc++, libc++]
            cppstd: [None, 98, gnu98, 11, gnu11, 14, gnu14, 17, gnu17, 20, gnu20]
        intel:
            version: ["11", "12", "13", "14", "15", "16", "17", "18", "19", "19.1"]
            base:
                gcc:
                    <<: *gcc
                    threads: [None]
                    exception: [None]
                Visual Studio:
                    <<: *visual_studio
                apple-clang:
                    <<: *apple_clang
        qcc:
            version: ["4.4", "5.4", "8.3"]
            libcxx: [cxx, gpp, cpp, cpp-ne, accp, acpp-ne, ecpp, ecpp-ne]
            cppstd: [None, 98, gnu98, 11, gnu11, 14, gnu14, 17, gnu17]
        mcst-lcc:
            version: ["1.19", "1.20", "1.21", "1.22", "1.23", "1.24", "1.25"]
            base:
                gcc:
                    <<: *gcc
                    threads: [None]
                    exceptions: [None]

    build_type: [None, Debug, Release, RelWithDebInfo, MinSizeRel]

    {% if not conan_v2 %}
    cppstd: [None, 98, gnu98, 11, gnu11, 14, gnu14, 17, gnu17, 20, gnu20]  # Deprecated, use compiler.cppstd
    {% endif %}
    """))


def get_default_settings_yml(force_v1=False):
    conan_v2 = not force_v1 and os.environ.get(CONAN_V2_MODE_ENVVAR, False)
    return _t_default_settings_yml.render(conan_v2=conan_v2)


_t_default_client_conf = Template(textwrap.dedent("""
    [log]
    run_to_output = True        # environment CONAN_LOG_RUN_TO_OUTPUT
    run_to_file = False         # environment CONAN_LOG_RUN_TO_FILE
    level = critical            # environment CONAN_LOGGING_LEVEL
    # trace_file =              # environment CONAN_TRACE_FILE
    print_run_commands = False  # environment CONAN_PRINT_RUN_COMMANDS

    [general]
    default_profile = {{default_profile}}
    compression_level = 9                 # environment CONAN_COMPRESSION_LEVEL
    sysrequires_sudo = True               # environment CONAN_SYSREQUIRES_SUDO
    request_timeout = 60                  # environment CONAN_REQUEST_TIMEOUT (seconds)
    default_package_id_mode = semver_direct_mode # environment CONAN_DEFAULT_PACKAGE_ID_MODE
    # retry = 2                             # environment CONAN_RETRY
    # retry_wait = 5                        # environment CONAN_RETRY_WAIT (seconds)
    # sysrequires_mode = enabled          # environment CONAN_SYSREQUIRES_MODE (allowed modes enabled/verify/disabled)
    # vs_installation_preference = Enterprise, Professional, Community, BuildTools # environment CONAN_VS_INSTALLATION_PREFERENCE
    # verbose_traceback = False           # environment CONAN_VERBOSE_TRACEBACK
    # error_on_override = False           # environment CONAN_ERROR_ON_OVERRIDE
    # bash_path = ""                      # environment CONAN_BASH_PATH (only windows)
    # read_only_cache = True              # environment CONAN_READ_ONLY_CACHE
    # cache_no_locks = True               # environment CONAN_CACHE_NO_LOCKS
    # user_home_short = your_path         # environment CONAN_USER_HOME_SHORT
    # use_always_short_paths = False      # environment CONAN_USE_ALWAYS_SHORT_PATHS
    # skip_vs_projects_upgrade = False    # environment CONAN_SKIP_VS_PROJECTS_UPGRADE
    # non_interactive = False             # environment CONAN_NON_INTERACTIVE
    # skip_broken_symlinks_check = False  # environment CONAN_SKIP_BROKEN_SYMLINKS_CHECK

    # conan_make_program = make           # environment CONAN_MAKE_PROGRAM (overrides the make program used in AutoToolsBuildEnvironment.make)
    # conan_cmake_program = cmake         # environment CONAN_CMAKE_PROGRAM (overrides the make program used in CMake.cmake_program)

    # cmake_generator                     # environment CONAN_CMAKE_GENERATOR
    # cmake generator platform            # environment CONAN_CMAKE_GENERATOR_PLATFORM
    # http://www.vtk.org/Wiki/CMake_Cross_Compiling
    # cmake_toolchain_file                # environment CONAN_CMAKE_TOOLCHAIN_FILE
    # cmake_system_name                   # environment CONAN_CMAKE_SYSTEM_NAME
    # cmake_system_version                # environment CONAN_CMAKE_SYSTEM_VERSION
    # cmake_system_processor              # environment CONAN_CMAKE_SYSTEM_PROCESSOR
    # cmake_find_root_path                # environment CONAN_CMAKE_FIND_ROOT_PATH
    # cmake_find_root_path_mode_program   # environment CONAN_CMAKE_FIND_ROOT_PATH_MODE_PROGRAM
    # cmake_find_root_path_mode_library   # environment CONAN_CMAKE_FIND_ROOT_PATH_MODE_LIBRARY
    # cmake_find_root_path_mode_include   # environment CONAN_CMAKE_FIND_ROOT_PATH_MODE_INCLUDE

    # msbuild_verbosity = minimal         # environment CONAN_MSBUILD_VERBOSITY

    # cpu_count = 1             # environment CONAN_CPU_COUNT

    # Change the default location for building test packages to a temporary folder
    # which is deleted after the test.
    # temp_test_folder = True             # environment CONAN_TEMP_TEST_FOLDER

    # cacert_path                         # environment CONAN_CACERT_PATH
    # scm_to_conandata                    # environment CONAN_SCM_TO_CONANDATA
    {% if conan_v2 %}
    revisions_enabled = 1
    {% endif %}

    # config_install_interval = 1h
    # required_conan_version = >=1.26

    # keep_python_files = False           # environment CONAN_KEEP_PYTHON_FILES

    [storage]
    # This is the default path, but you can write your own. It must be an absolute path or a
    # path beginning with "~" (if the environment var CONAN_USER_HOME is specified, this directory, even
    # with "~/", will be relative to the conan user home, not to the system user home)
    path = ./data

    [proxies]
    # Empty (or missing) section will try to use system proxies.
    # As documented in https://requests.readthedocs.io/en/master/user/advanced/#proxies - but see below
    # for proxies to specific hosts
    # http = http://user:pass@10.10.1.10:3128/
    # http = http://10.10.1.10:3128
    # https = http://10.10.1.10:1080
    # To specify a proxy for a specific host or hosts, use multiple lines each specifying host = proxy-spec
    # http =
    #   hostname.to.be.proxied.com = http://user:pass@10.10.1.10:3128
    # You can skip the proxy for the matching (fnmatch) urls (comma-separated)
    # no_proxy_match = *bintray.com*, https://myserver.*

    {% if not conan_v2 %}{# no hooks by default in Conan v2 #}
    [hooks]    # environment CONAN_HOOKS
    attribute_checker
    {% endif %}

    # Default settings now declared in the default profile
    """))


def get_default_client_conf(force_v1=False):
    conan_v2 = not force_v1 and os.environ.get(CONAN_V2_MODE_ENVVAR, False)
    return _t_default_client_conf.render(conan_v2=conan_v2, default_profile=DEFAULT_PROFILE_NAME)


class ConanClientConfigParser(ConfigParser, object):

    # So keys are not converted to lowercase, we override the default optionxform
    optionxform = str

    _table_vars = {
        # Environment variable | conan.conf variable | Default value
        "log": [
            ("CONAN_LOG_RUN_TO_OUTPUT", "run_to_output", True),
            ("CONAN_LOG_RUN_TO_FILE", "run_to_file", False),
            ("CONAN_LOGGING_LEVEL", "level", logging.CRITICAL),
            ("CONAN_TRACE_FILE", "trace_file", None),
            ("CONAN_PRINT_RUN_COMMANDS", "print_run_commands", False),
        ],
        "general": [
            ("CONAN_COMPRESSION_LEVEL", "compression_level", 9),
            ("CONAN_NON_INTERACTIVE", "non_interactive", False),
            ("CONAN_SKIP_BROKEN_SYMLINKS_CHECK", "skip_broken_symlinks_check", False),
            ("CONAN_CACHE_NO_LOCKS", "cache_no_locks", False),
            ("CONAN_SYSREQUIRES_SUDO", "sysrequires_sudo", False),
            ("CONAN_SYSREQUIRES_MODE", "sysrequires_mode", None),
            ("CONAN_REQUEST_TIMEOUT", "request_timeout", None),
            ("CONAN_RETRY", "retry", None),
            ("CONAN_RETRY_WAIT", "retry_wait", None),
            ("CONAN_VS_INSTALLATION_PREFERENCE", "vs_installation_preference", None),
            ("CONAN_CPU_COUNT", "cpu_count", None),
            ("CONAN_READ_ONLY_CACHE", "read_only_cache", None),
            ("CONAN_USER_HOME_SHORT", "user_home_short", None),
            ("CONAN_USE_ALWAYS_SHORT_PATHS", "use_always_short_paths", None),
            ("CONAN_VERBOSE_TRACEBACK", "verbose_traceback", None),
            ("CONAN_ERROR_ON_OVERRIDE", "error_on_override", False),
            # http://www.vtk.org/Wiki/CMake_Cross_Compiling
            ("CONAN_CMAKE_GENERATOR", "cmake_generator", None),
            ("CONAN_CMAKE_GENERATOR_PLATFORM", "cmake_generator_platform", None),
            ("CONAN_CMAKE_TOOLCHAIN_FILE", "cmake_toolchain_file", None),
            ("CONAN_CMAKE_SYSTEM_NAME", "cmake_system_name", None),
            ("CONAN_CMAKE_SYSTEM_VERSION", "cmake_system_version", None),
            ("CONAN_CMAKE_SYSTEM_PROCESSOR", "cmake_system_processor", None),
            ("CONAN_CMAKE_FIND_ROOT_PATH", "cmake_find_root_path", None),
            ("CONAN_CMAKE_FIND_ROOT_PATH_MODE_PROGRAM", "cmake_find_root_path_mode_program", None),
            ("CONAN_CMAKE_FIND_ROOT_PATH_MODE_LIBRARY", "cmake_find_root_path_mode_library", None),
            ("CONAN_CMAKE_FIND_ROOT_PATH_MODE_INCLUDE", "cmake_find_root_path_mode_include", None),
            ("CONAN_BASH_PATH", "bash_path", None),
            ("CONAN_MAKE_PROGRAM", "conan_make_program", None),
            ("CONAN_CMAKE_PROGRAM", "conan_cmake_program", None),
            ("CONAN_TEMP_TEST_FOLDER", "temp_test_folder", False),
            ("CONAN_SKIP_VS_PROJECTS_UPGRADE", "skip_vs_projects_upgrade", False),
            ("CONAN_MSBUILD_VERBOSITY", "msbuild_verbosity", None),
            ("CONAN_CACERT_PATH", "cacert_path", None),
            ("CONAN_DEFAULT_PACKAGE_ID_MODE", "default_package_id_mode", None),
            ("CONAN_KEEP_PYTHON_FILES", "keep_python_files", False),
            # ("CONAN_DEFAULT_PROFILE_PATH", "default_profile", DEFAULT_PROFILE_NAME),
        ],
        "hooks": [
            ("CONAN_HOOKS", "", None),
        ]
    }

    def __init__(self, filename):
        super(ConanClientConfigParser, self).__init__(allow_no_value=True)
        self.read(filename)
        self.filename = filename

    @property
    def env_vars(self):
        ret = {}
        for section, values in self._table_vars.items():
            for env_var, var_name, default_value in values:
                var_name = ".".join([section, var_name]) if var_name else section
                value = self._env_c(var_name, env_var, default_value)
                if value is not None:
                    ret[env_var] = str(value)
        return ret

    def _env_c(self, var_name, env_var_name, default_value):
        """ Returns the value Conan will use: first tries with environment variable,
            then value written in 'conan.conf' and fallback to 'default_value'
        """
        env = os.environ.get(env_var_name, None)
        if env is not None:
            return env
        try:
            return unquote(self.get_item(var_name))
        except ConanException:
            return default_value

    def get_item(self, item):
        """ Return the value stored in 'conan.conf' """
        if not item:
            return load(self.filename)

        tokens = item.split(".", 1)
        section_name = tokens[0]
        try:
            section = self.items(section_name)
        except NoSectionError:
            raise ConanException("'%s' is not a section of conan.conf" % section_name)
        if len(tokens) == 1:
            result = []
            if section_name == "hooks":
                for key, _ in section:
                    result.append(key)
                return ",".join(result)
            else:
                for section_item in section:
                    result.append(" = ".join(section_item))
                return "\n".join(result)
        else:
            key = tokens[1]
            try:
                value = dict(section)[key]
                if " #" in value:  # Comments
                    value = value[:value.find(" #")].strip()
            except KeyError:
                raise ConanException("'%s' doesn't exist in [%s]" % (key, section_name))
            return value

    def set_item(self, key, value):
        tokens = key.split(".", 1)
        if len(tokens) == 1:  # defining full section
            raise ConanException("You can't set a full section, please specify a section.key=value")

        section_name = tokens[0]
        if not self.has_section(section_name):
            self.add_section(section_name)

        key = tokens[1]
        try:
            super(ConanClientConfigParser, self).set(section_name, key, value)
        except ValueError:
            # https://github.com/conan-io/conan/issues/4110
            value = value.replace("%", "%%")
            super(ConanClientConfigParser, self).set(section_name, key, value)

        with open(self.filename, "w") as f:
            self.write(f)

    def rm_item(self, item):
        tokens = item.split(".", 1)
        section_name = tokens[0]
        if not self.has_section(section_name):
            raise ConanException("'%s' is not a section of conan.conf" % section_name)

        if len(tokens) == 1:
            self.remove_section(tokens[0])
        else:
            key = tokens[1]
            if not self.has_option(section_name, key):
                raise ConanException("'%s' doesn't exist in [%s]" % (key, section_name))
            self.remove_option(section_name, key)

        with open(self.filename, "w") as f:
            self.write(f)

    def _get_conf(self, varname):
        """Gets the section from config file or raises an exception"""
        try:
            return self.items(varname)
        except NoSectionError:
            raise ConanException("Invalid configuration, missing %s" % varname)

    @property
    def default_profile(self):
        ret = os.environ.get("CONAN_DEFAULT_PROFILE_PATH", None)
        if ret:
            if not os.path.isabs(ret):
                from conans.client.cache.cache import PROFILES_FOLDER
                profiles_folder = os.path.join(os.path.dirname(self.filename), PROFILES_FOLDER)
                ret = os.path.abspath(os.path.join(profiles_folder, ret))

            if not os.path.exists(ret):
                raise ConanException("Environment variable 'CONAN_DEFAULT_PROFILE_PATH' "
                                     "must point to an existing profile file.")
            return ret
        else:
            try:
                return unquote(self.get_item("general.default_profile"))
            except ConanException:
                return DEFAULT_PROFILE_NAME

    @property
    def cache_no_locks(self):
        try:
            return get_env("CONAN_CACHE_NO_LOCKS", False)
        except ConanException:
            return False

    @property
    def request_timeout(self):
        timeout = os.getenv("CONAN_REQUEST_TIMEOUT")
        if not timeout:
            try:
                timeout = self.get_item("general.request_timeout")
            except ConanException:
                return None

        try:
            return float(timeout) if timeout is not None else None
        except ValueError:
            raise ConanException("Specify a numeric parameter for 'request_timeout'")

    @property
    def revisions_enabled(self):
        try:
            revisions_enabled = get_env("CONAN_REVISIONS_ENABLED")
            if revisions_enabled is None:
                revisions_enabled = self.get_item("general.revisions_enabled")
            return revisions_enabled.lower() in ("1", "true")
        except ConanException:
            return True if os.environ.get(CONAN_V2_MODE_ENVVAR, False) else False

    @property
    def parallel_download(self):
        try:
            parallel = self.get_item("general.parallel_download")
        except ConanException:
            return None

        try:
            return int(parallel) if parallel is not None else None
        except ValueError:
            raise ConanException("Specify a numeric parameter for 'parallel_download'")

    @property
    def download_cache(self):
        try:
            download_cache = self.get_item("storage.download_cache")
            return download_cache
        except ConanException:
            return None

    @property
    def scm_to_conandata(self):
        try:
            scm_to_conandata = get_env("CONAN_SCM_TO_CONANDATA")
            if scm_to_conandata is None:
                scm_to_conandata = self.get_item("general.scm_to_conandata")
            return scm_to_conandata.lower() in ("1", "true")
        except ConanException:
            return True if os.environ.get(CONAN_V2_MODE_ENVVAR, False) else False

    @property
    def default_package_id_mode(self):
        try:
            default_package_id_mode = get_env("CONAN_DEFAULT_PACKAGE_ID_MODE")
            if default_package_id_mode is None:
                default_package_id_mode = self.get_item("general.default_package_id_mode")
            return default_package_id_mode
        except ConanException:
            return "semver_direct_mode"

    @property
    def default_python_requires_id_mode(self):
        try:
            default_package_id_mode = get_env("CONAN_DEFAULT_PYTHON_REQUIRES_ID_MODE")
            if default_package_id_mode is None:
                default_package_id_mode = self.get_item("general.default_python_requires_id_mode")
        except ConanException:
            return "minor_mode"
        return default_package_id_mode

    @property
    def full_transitive_package_id(self):
        try:
            fix_id = self.get_item("general.full_transitive_package_id")
            return fix_id.lower() in ("1", "true")
        except ConanException:
            return None

    @property
    def msvc_visual_incompatible(self):
        try:
            visual_comp = self.get_item("general.msvc_visual_incompatible")
            return visual_comp.lower() in ("1", "true")
        except ConanException:
            return False

    @property
    def short_paths_home(self):
        short_paths_home = get_env("CONAN_USER_HOME_SHORT")
        if short_paths_home:
            current_dir = os.path.dirname(os.path.normpath(os.path.normcase(self.filename)))
            short_paths_dir = os.path.normpath(os.path.normcase(short_paths_home))
            if current_dir == short_paths_dir  or \
                    short_paths_dir.startswith(current_dir + os.path.sep):
                raise ConanException("Short path home '{}' (defined by conan.conf variable "
                                     "'user_home_short', or environment variable "
                                     "'CONAN_USER_HOME_SHORT') cannot be a subdirectory of "
                                     "the conan cache '{}'.".format(short_paths_home, current_dir))
        return short_paths_home

    @property
    def storage_path(self):
        # Try with CONAN_STORAGE_PATH
        result = get_env('CONAN_STORAGE_PATH', None)
        if not result:
            # Try with conan.conf "path"
            try:
                # TODO: Fix this mess for Conan 2.0
                env_conan_user_home = os.getenv("CONAN_USER_HOME")
                current_dir = os.path.dirname(self.filename)
                # if env var is declared, any specified path will be relative to CONAN_USER_HOME
                # even with the ~/
                result = dict(self._get_conf("storage"))["path"]
                if result.startswith("."):
                    result = os.path.abspath(os.path.join(current_dir, result))
                elif result[:2] == "~/":
                    if env_conan_user_home:
                        result = os.path.join(env_conan_user_home, result[2:])
            except (KeyError, ConanException):  # If storage not defined, to return None
                pass

        if result:
            result = conan_expand_user(result)
            if not os.path.isabs(result):
                raise ConanException("Conan storage path has to be an absolute path")
        return result

    @property
    def proxies(self):
        try:  # optional field, might not exist
            proxies = self._get_conf("proxies")
        except Exception:
            return None
        result = {}
        # Handle proxy specifications of the form:
        # http = http://proxy.xyz.com
        #   special-host.xyz.com = http://special-proxy.xyz.com
        # (where special-proxy.xyz.com is only used as a proxy when special-host.xyz.com)
        for scheme, proxy_string in proxies or []:
            if proxy_string is None or proxy_string == "None":
                result[scheme] = None
            else:
                for line in proxy_string.splitlines():
                    proxy_value = [t.strip() for t in line.split("=", 1)]
                    if len(proxy_value) == 2:
                        result[scheme+"://"+proxy_value[0]] = proxy_value[1]
                    elif proxy_value[0]:
                        result[scheme] = proxy_value[0]
        return result

    @property
    def cacert_path(self):
        try:
            cacert_path = get_env("CONAN_CACERT_PATH")
            if not cacert_path:
                cacert_path = self.get_item("general.cacert_path")
        except ConanException:
            cacert_path = os.path.join(os.path.dirname(self.filename), CACERT_FILE)
        else:
            # For explicit cacert files, the file should already exist
            if not os.path.exists(cacert_path):
                raise ConanException("Configured file for 'cacert_path'"
                                     " doesn't exists: '{}'".format(cacert_path))
        return cacert_path

    @property
    def client_cert_path(self):
        cache_folder = os.path.dirname(self.filename)
        try:
            path = self.get_item("general.client_cert_path")
        except ConanException:
            path = os.path.join(cache_folder, "client.crt")
        else:
            # For explicit cacert files, the file should already exist
            path = os.path.join(cache_folder, path)
            if not os.path.exists(path):
                raise ConanException("Configured file for 'client_cert_path'"
                                     " doesn't exists: '{}'".format(path))
        return os.path.normpath(path)

    @property
    def client_cert_key_path(self):
        cache_folder = os.path.dirname(self.filename)
        try:
            path = self.get_item("general.client_cert_key_path")
        except ConanException:
            path = os.path.join(cache_folder, "client.key")
        else:
            # For explicit cacert files, the file should already exist
            path = os.path.join(cache_folder, path)
            if not os.path.exists(path):
                raise ConanException("Configured file for 'client_cert_key_path'"
                                     " doesn't exists: '{}'".format(path))
        return os.path.normpath(path)

    @property
    def hooks(self):
        hooks = get_env("CONAN_HOOKS", list())
        if not hooks:
            try:
                hooks = self._get_conf("hooks")
                hooks = [k for k, _ in hooks]
            except Exception:
                hooks = []
        return hooks

    @property
    def non_interactive(self):
        try:
            non_interactive = get_env("CONAN_NON_INTERACTIVE")
            if non_interactive is None:
                non_interactive = self.get_item("general.non_interactive")
            return non_interactive.lower() in ("1", "true")
        except ConanException:
            return False

    @property
    def logging_level(self):
        try:
            level = get_env("CONAN_LOGGING_LEVEL")
            if level is None:
                level = self.get_item("log.level")
            try:
                parsed_level = ConanClientConfigParser.get_log_level_by_name(level)
                level = parsed_level if parsed_level is not None else int(level)
            except Exception:
                level = logging.CRITICAL
            return level
        except ConanException:
            return logging.CRITICAL

    @property
    def logging_file(self):
        return get_env('CONAN_LOGGING_FILE', None)

    @property
    def print_commands_to_output(self):
        try:
            print_commands_to_output = get_env("CONAN_PRINT_RUN_COMMANDS")
            if print_commands_to_output is None:
                print_commands_to_output = self.get_item("log.print_run_commands")
            return print_commands_to_output.lower() in ("1", "true")
        except ConanException:
            return False

    @property
    def retry(self):
        retry = os.getenv("CONAN_RETRY")
        if not retry:
            try:
                retry = self.get_item("general.retry")
            except ConanException:
                return None

        try:
            return int(retry) if retry is not None else None
        except ValueError:
            raise ConanException("Specify a numeric parameter for 'retry'")

    @property
    def retry_wait(self):
        retry_wait = os.getenv("CONAN_RETRY_WAIT")
        if not retry_wait:
            try:
                retry_wait = self.get_item("general.retry_wait")
            except ConanException:
                return None

        try:
            return int(retry_wait) if retry_wait is not None else None
        except ValueError:
            raise ConanException("Specify a numeric parameter for 'retry_wait'")

    @property
    def generate_run_log_file(self):
        try:
            generate_run_log_file = get_env("CONAN_LOG_RUN_TO_FILE")
            if generate_run_log_file is None:
                generate_run_log_file = self.get_item("log.run_to_file")
            return generate_run_log_file.lower() in ("1", "true")
        except ConanException:
            return False

    @property
    def log_run_to_output(self):
        try:
            log_run_to_output = get_env("CONAN_LOG_RUN_TO_OUTPUT")
            if log_run_to_output is None:
                log_run_to_output = self.get_item("log.run_to_output")
            return log_run_to_output.lower() in ("1", "true")
        except ConanException:
            return True

    @staticmethod
    def get_log_level_by_name(level_name):
        levels = {
            "critical": logging.CRITICAL,
            "error": logging.ERROR,
            "warning": logging.WARNING,
            "warn": logging.WARNING,
            "info": logging.INFO,
            "debug": logging.DEBUG,
            "notset": logging.NOTSET
        }
        return levels.get(str(level_name).lower())

    @property
    def config_install_interval(self):
        try:
            interval = self.get_item("general.config_install_interval")
        except ConanException:
            return None

        try:
            return timedelta_from_text(interval)
        except Exception:
            raise ConanException("Incorrect definition of general.config_install_interval: %s"
                                 % interval)

    @property
    def required_conan_version(self):
        try:
            return self.get_item("general.required_conan_version")
        except ConanException:
            return None
