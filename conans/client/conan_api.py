import os
import sys
from collections import OrderedDict

from conans.paths.package_layouts.package_cache_layout import PackageCacheLayout

import conans
from conans import __version__ as client_version
from conans.client import packager, tools
from conans.client.cache.cache import ClientCache
from conans.client.cmd.build import build
from conans.client.cmd.create import create
from conans.client.cmd.download import download
from conans.client.cmd.export import cmd_export, export_alias
from conans.client.cmd.export_pkg import export_pkg
from conans.client.cmd.profile import (cmd_profile_create, cmd_profile_delete_key, cmd_profile_get,
                                       cmd_profile_list, cmd_profile_update)
from conans.client.cmd.search import Search
from conans.client.cmd.test import PackageTester
from conans.client.cmd.uploader import CmdUpload
from conans.client.cmd.user import user_set, users_clean, users_list, token_present
from conans.client.conf import ConanClientConfigParser
from conans.client.graph.graph import RECIPE_EDITABLE
from conans.client.graph.graph_manager import GraphManager
from conans.client.graph.printer import print_graph
from conans.client.graph.proxy import ConanProxy
from conans.client.graph.python_requires import ConanPythonRequire
from conans.client.graph.range_resolver import RangeResolver
from conans.client.hook_manager import HookManager
from conans.client.importer import run_imports, undo_imports
from conans.client.installer import BinaryInstaller
from conans.client.loader import ConanFileLoader
from conans.client.manager import ConanManager
from conans.client.migrations import ClientMigrator
from conans.client.output import ConanOutput, colorama_initialize
from conans.client.profile_loader import profile_from_args, read_profile
from conans.client.recorder.action_recorder import ActionRecorder
from conans.client.recorder.search_recorder import SearchRecorder
from conans.client.recorder.upload_recoder import UploadRecorder
from conans.client.remote_manager import RemoteManager
from conans.client.remover import ConanRemover
from conans.client.rest.auth_manager import ConanApiAuthManager
from conans.client.rest.conan_requester import ConanRequester
from conans.client.rest.rest_client import RestApiClient
from conans.client.runner import ConanRunner
from conans.client.source import config_source_local
from conans.client.store.localdb import LocalDB
from conans.client.userio import UserIO
from conans.errors import (ConanException, RecipeNotFoundException,
                           PackageNotFoundException, NoRestV2Available, NotFoundException)
from conans.model.conan_file import get_env_context_manager
from conans.model.editable_layout import get_editable_abs_path
from conans.model.graph_info import GraphInfo, GRAPH_INFO_FILE
from conans.model.graph_lock import GraphLockFile, LOCKFILE
from conans.model.ref import ConanFileReference, PackageReference, check_valid_ref
from conans.model.version import Version
from conans.model.workspace import Workspace
from conans.paths import BUILD_INFO, CONANINFO, get_conan_user_home
from conans.search.search import search_recipes
from conans.tools import set_global_instances
from conans.unicode import get_cwd
from conans.util.files import exception_message_safe, mkdir, save_files
from conans.util.log import configure_logger
from conans.util.tracer import log_command, log_exception


default_manifest_folder = '.conan_manifests'


def api_method(f):
    def wrapper(*args, **kwargs):
        api = args[0]
        api.create_app()
        try:
            curdir = get_cwd()
            log_command(f.__name__, kwargs)
            with tools.environment_append(api.app.cache.config.env_vars):
                return f(*args, **kwargs)
        except Exception as exc:
            msg = exception_message_safe(exc)
            try:
                log_exception(exc, msg)
            except BaseException:
                pass
            raise
        finally:
            os.chdir(curdir)
    return wrapper


def _make_abs_path(path, cwd=None, default=None):
    """convert 'path' to absolute if necessary (could be already absolute)
    if not defined (empty, or None), will return 'default' one or 'cwd'
    """
    cwd = cwd or get_cwd()
    if not path:
        abs_path = default or cwd
    elif os.path.isabs(path):
        abs_path = path
    else:
        abs_path = os.path.normpath(os.path.join(cwd, path))
    return abs_path


def _get_conanfile_path(path, cwd, py):
    """
    param py= True: Must be .py, False: Must be .txt, None: Try .py, then .txt
    """
    candidate_paths = list()
    path = _make_abs_path(path, cwd)

    if os.path.isdir(path):  # Can be a folder
        if py:
            path = os.path.join(path, "conanfile.py")
            candidate_paths.append(path)
        elif py is False:
            path = os.path.join(path, "conanfile.txt")
            candidate_paths.append(path)
        else:
            path_py = os.path.join(path, "conanfile.py")
            candidate_paths.append(path_py)
            if os.path.exists(path_py):
                path = path_py
            else:
                path = os.path.join(path, "conanfile.txt")
                candidate_paths.append(path)
    else:
        candidate_paths.append(path)

    if not os.path.isfile(path):  # Must exist
        raise ConanException("Conanfile not found at %s" % " or ".join(candidate_paths))

    if py and not path.endswith(".py"):
        raise ConanException("A conanfile.py is needed, " + path + " is not acceptable")

    return path


class ConanApp(object):
    def __init__(self, cache_folder, user_io, http_requester=None, runner=None):
        # User IO, interaction and logging
        self.user_io = user_io
        self.out = self.user_io.out
        self.cache_folder = cache_folder
        self.cache = ClientCache(self.cache_folder, self.out)
        self.config = self.cache.config
        interactive = not self.config.non_interactive
        if not interactive:
            self.user_io.disable_input()

        # Adjust CONAN_LOGGING_LEVEL with the env readed
        conans.util.log.logger = configure_logger(self.config.logging_level,
                                                  self.config.logging_file)
        conans.util.log.logger.debug("INIT: Using config '%s'" % self.cache.conan_conf_path)

        self.hook_manager = HookManager(self.cache.hooks_path, self.config.hooks, self.out)
        # Wraps an http_requester to inject proxies, certs, etc
        self.requester = ConanRequester(self.config, http_requester)
        # To handle remote connections
        put_headers = self.cache.read_put_headers()
        rest_api_client = RestApiClient(self.out, self.requester,
                                        revisions_enabled=self.config.revisions_enabled,
                                        put_headers=put_headers)
        # To store user and token
        localdb = LocalDB.create(self.cache.localdb)
        # Wraps RestApiClient to add authentication support (same interface)
        auth_manager = ConanApiAuthManager(rest_api_client, self.user_io, localdb)
        # Handle remote connections
        self.remote_manager = RemoteManager(self.cache, auth_manager, self.out, self.hook_manager)

        # Adjust global tool variables
        set_global_instances(self.out, self.requester)

        self.runner = runner or ConanRunner(self.config.print_commands_to_output,
                                            self.config.generate_run_log_file,
                                            self.config.log_run_to_output,
                                            self.out)

        self.proxy = ConanProxy(self.cache, self.out, self.remote_manager)
        resolver = RangeResolver(self.cache, self.remote_manager)
        self.python_requires = ConanPythonRequire(self.proxy, resolver)
        self.loader = ConanFileLoader(self.runner, self.out, self.python_requires)

        self.graph_manager = GraphManager(self.out, self.cache,
                                          self.remote_manager, self.loader, self.proxy,
                                          resolver)


class ConanAPIV1(object):
    @classmethod
    def factory(cls):
        return cls(), None, None

    def __init__(self, cache_folder=None, output=None, user_io=None, http_requester=None,
                 runner=None):
        color = colorama_initialize()
        self.out = output or ConanOutput(sys.stdout, sys.stderr, color)
        self.user_io = user_io or UserIO(out=self.out)
        self.cache_folder = cache_folder or os.path.join(get_conan_user_home(), ".conan")
        cache = ClientCache(self.cache_folder, self.out)
        self.http_requester = http_requester
        self.runner = runner
        self.app = None  # Api calls will create a new one every call
        # Migration system
        migrator = ClientMigrator(cache, Version(client_version), self.out)
        migrator.migrate()
        # Remove in Conan 2.0
        sys.path.append(os.path.join(cache.cache_folder, "python"))

    def create_app(self):
        self.app = ConanApp(self.cache_folder, self.user_io, self.http_requester, self.runner)

    def _init_manager(self, action_recorder):
        """Every api call gets a new recorder and new manager"""
        return ConanManager(self.app.cache, self.app.user_io,
                            self.app.remote_manager, action_recorder,
                            self.app.graph_manager, self.app.hook_manager)

    @api_method
    def new(self, name, header=False, pure_c=False, test=False, exports_sources=False, bare=False,
            cwd=None, visual_versions=None, linux_gcc_versions=None, linux_clang_versions=None,
            osx_clang_versions=None, shared=None, upload_url=None, gitignore=None,
            gitlab_gcc_versions=None, gitlab_clang_versions=None,
            circleci_gcc_versions=None, circleci_clang_versions=None, circleci_osx_versions=None,
            template=None):
        from conans.client.cmd.new import cmd_new
        cwd = os.path.abspath(cwd or get_cwd())
        files = cmd_new(name, header=header, pure_c=pure_c, test=test,
                        exports_sources=exports_sources, bare=bare,
                        visual_versions=visual_versions,
                        linux_gcc_versions=linux_gcc_versions,
                        linux_clang_versions=linux_clang_versions,
                        osx_clang_versions=osx_clang_versions, shared=shared,
                        upload_url=upload_url, gitignore=gitignore,
                        gitlab_gcc_versions=gitlab_gcc_versions,
                        gitlab_clang_versions=gitlab_clang_versions,
                        circleci_gcc_versions=circleci_gcc_versions,
                        circleci_clang_versions=circleci_clang_versions,
                        circleci_osx_versions=circleci_osx_versions,
                        template=template, cache=self.app.cache)

        save_files(cwd, files)
        for f in sorted(files):
            self.app.out.success("File saved: %s" % f)

    @api_method
    def inspect(self, path, attributes, remote_name=None):
        remotes = self.app.cache.registry.load_remotes()
        remotes.select(remote_name)
        self.app.python_requires.enable_remotes(remotes=remotes)
        try:
            ref = ConanFileReference.loads(path)
        except ConanException:
            conanfile_path = _get_conanfile_path(path, get_cwd(), py=True)
            ref = os.path.basename(conanfile_path)
            conanfile_class = self.app.loader.load_class(conanfile_path)
        else:
            update = True if remote_name else False
            result = self.app.proxy.get_recipe(ref, update, update, remotes, ActionRecorder())
            conanfile_path, _, _, ref = result
            conanfile_class = self.app.loader.load_class(conanfile_path)
            conanfile_class.name = ref.name
            conanfile_class.version = ref.version

        conanfile = conanfile_class(self.app.out, None, repr(ref))

        result = OrderedDict()
        if not attributes:
            attributes = ['name', 'version', 'url', 'homepage', 'license', 'author',
                          'description', 'topics', 'generators', 'exports', 'exports_sources',
                          'short_paths', 'apply_env', 'build_policy', 'revision_mode', 'settings',
                          'options', 'default_options']
        for attribute in attributes:
            try:
                attr = getattr(conanfile, attribute)
                result[attribute] = attr
            except AttributeError:
                result[attribute] = ''
        return result

    @api_method
    def test(self, path, reference, profile_names=None, settings=None, options=None, env=None,
             remote_name=None, update=False, build_modes=None, cwd=None, test_build_folder=None,
             lockfile=None):

        settings = settings or []
        options = options or []
        env = env or []

        remotes = self.app.cache.registry.load_remotes()
        remotes.select(remote_name)
        self.app.python_requires.enable_remotes(update=update, remotes=remotes)

        conanfile_path = _get_conanfile_path(path, cwd, py=True)
        cwd = cwd or get_cwd()
        lockfile = _make_abs_path(lockfile, cwd) if lockfile else None
        graph_info = get_graph_info(profile_names, settings, options, env, cwd, None,
                                    self.app.cache, self.app.out, lockfile=lockfile)
        ref = ConanFileReference.loads(reference)
        recorder = ActionRecorder()
        manager = self._init_manager(recorder)
        pt = PackageTester(manager, self.user_io)
        pt.install_build_and_test(conanfile_path, ref, graph_info, remotes,
                                  update, build_modes=build_modes,
                                  test_build_folder=test_build_folder)

    @api_method
    def create(self, conanfile_path, name=None, version=None, user=None, channel=None,
               profile_names=None, settings=None,
               options=None, env=None, test_folder=None, not_export=False,
               build_modes=None,
               keep_source=False, keep_build=False, verify=None,
               manifests=None, manifests_interactive=None,
               remote_name=None, update=False, cwd=None, test_build_folder=None,
               lockfile=None):
        """
        API method to create a conan package

        :param test_folder: default None   - looks for default 'test' or 'test_package' folder),
                                    string - test_folder path
                                    False  - disabling tests
        """
        settings = settings or []
        options = options or []
        env = env or []

        try:
            cwd = cwd or os.getcwd()
            recorder = ActionRecorder()
            conanfile_path = _get_conanfile_path(conanfile_path, cwd, py=True)

            remotes = self.app.cache.registry.load_remotes()
            remotes.select(remote_name)
            self.app.python_requires.enable_remotes(update=update, remotes=remotes)

            lockfile = _make_abs_path(lockfile, cwd) if lockfile else None
            graph_info = get_graph_info(profile_names, settings, options, env, cwd, None,
                                        self.app.cache, self.app.out, lockfile=lockfile)

            # Make sure keep_source is set for keep_build
            keep_source = keep_source or keep_build
            new_ref = cmd_export(conanfile_path, name, version, user, channel, keep_source,
                                 self.app.cache.config.revisions_enabled, self.app.out,
                                 self.app.hook_manager, self.app.loader, self.app.cache, not not_export,
                                 graph_lock=graph_info.graph_lock)

            # The new_ref contains the revision
            # To not break existing things, that they used this ref without revision
            ref = new_ref.copy_clear_rev()
            recorder.recipe_exported(new_ref)

            if build_modes is None:  # Not specified, force build the tested library
                build_modes = [ref.name]

            manifests = _parse_manifests_arguments(verify, manifests, manifests_interactive, cwd)
            manifest_folder, manifest_interactive, manifest_verify = manifests

            # FIXME: Dirty hack: remove the root for the test_package/conanfile.py consumer
            graph_info.root = ConanFileReference(None, None, None, None, validate=False)
            manager = self._init_manager(recorder)
            recorder.add_recipe_being_developed(ref)
            create(ref, manager, self.user_io, graph_info, remotes, update, build_modes,
                   manifest_folder, manifest_verify, manifest_interactive, keep_build,
                   test_build_folder, test_folder, conanfile_path)

            if lockfile:
                graph_info.save_lock(lockfile)
            return recorder.get_info(self.app.cache.config.revisions_enabled)

        except ConanException as exc:
            recorder.error = True
            exc.info = recorder.get_info(self.app.cache.config.revisions_enabled)
            raise

    @api_method
    def export_pkg(self, conanfile_path, name, channel, source_folder=None, build_folder=None,
                   package_folder=None, install_folder=None, profile_names=None, settings=None,
                   options=None, env=None, force=False, user=None, version=None, cwd=None,
                   lockfile=None):

        remotes = self.app.cache.registry.load_remotes()
        self.app.python_requires.enable_remotes(remotes=remotes)
        settings = settings or []
        options = options or []
        env = env or []
        cwd = cwd or get_cwd()

        try:
            recorder = ActionRecorder()
            conanfile_path = _get_conanfile_path(conanfile_path, cwd, py=True)

            if package_folder:
                if build_folder or source_folder:
                    raise ConanException("package folder definition incompatible with build "
                                         "and source folders")
                package_folder = _make_abs_path(package_folder, cwd)

            build_folder = _make_abs_path(build_folder, cwd)
            if install_folder:
                install_folder = _make_abs_path(install_folder, cwd)
            else:
                # FIXME: This is a hack for old UI, need to be fixed in Conan 2.0
                if os.path.exists(os.path.join(build_folder, GRAPH_INFO_FILE)):
                    install_folder = build_folder
            source_folder = _make_abs_path(source_folder, cwd,
                                           default=os.path.dirname(conanfile_path))

            lockfile = _make_abs_path(lockfile, cwd) if lockfile else None
            # Checks that no both settings and info files are specified
            graph_info = get_graph_info(profile_names, settings, options, env, cwd, install_folder,
                                        self.app.cache, self.app.out, lockfile=lockfile)

            new_ref = cmd_export(conanfile_path, name, version, user, channel, True,
                                 self.app.cache.config.revisions_enabled, self.app.out,
                                 self.app.hook_manager, self.app.loader, self.app.cache,
                                 graph_lock=graph_info.graph_lock)
            ref = new_ref.copy_clear_rev()
            # new_ref has revision
            recorder.recipe_exported(new_ref)
            recorder.add_recipe_being_developed(ref)
            remotes = self.app.cache.registry.load_remotes()
            export_pkg(self.app.cache, self.app.graph_manager, self.app.hook_manager, recorder,
                       self.app.out,
                       ref, source_folder=source_folder, build_folder=build_folder,
                       package_folder=package_folder, install_folder=install_folder,
                       graph_info=graph_info, force=force, remotes=remotes)
            if lockfile:
                graph_info.save_lock(lockfile)
            return recorder.get_info(self.app.cache.config.revisions_enabled)
        except ConanException as exc:
            recorder.error = True
            exc.info = recorder.get_info(self.app.cache.config.revisions_enabled)
            raise

    @api_method
    def download(self, reference, remote_name=None, packages=None, recipe=False):
        if packages and recipe:
            raise ConanException("recipe parameter cannot be used together with packages")
        # Install packages without settings (fixed ids or all)
        if check_valid_ref(reference):
            ref = ConanFileReference.loads(reference)
            if packages and ref.revision is None:
                for package_id in packages:
                    if "#" in package_id:
                        raise ConanException("It is needed to specify the recipe revision if you "
                                             "specify a package revision")
            remotes = self.app.cache.registry.load_remotes()
            remotes.select(remote_name)
            self.app.python_requires.enable_remotes(remotes=remotes)
            remote = remotes.get_remote(remote_name)
            recorder = ActionRecorder()
            download(ref, packages, remote, recipe, self.app.remote_manager,
                     self.app.cache, self.app.out, recorder, self.app.loader,
                     self.app.hook_manager, remotes=remotes)
        else:
            raise ConanException("Provide a valid full reference without wildcards.")

    @api_method
    def workspace_install(self, path, settings=None, options=None, env=None,
                          remote_name=None, build=None, profile_name=None,
                          update=False, cwd=None, install_folder=None):
        cwd = cwd or get_cwd()
        abs_path = os.path.normpath(os.path.join(cwd, path))

        remotes = self.app.cache.registry.load_remotes()
        remotes.select(remote_name)
        self.app.python_requires.enable_remotes(update=update, remotes=remotes)

        workspace = Workspace(abs_path, self.app.cache)
        graph_info = get_graph_info(profile_name, settings, options, env, cwd, None,
                                    self.app.cache, self.app.out)

        self.app.out.info("Configuration:")
        self.app.out.writeln(graph_info.profile.dumps())

        self.app.cache.editable_packages.override(workspace.get_editable_dict())

        recorder = ActionRecorder()
        deps_graph, _ = self.app.graph_manager.load_graph(workspace.root, None, graph_info, build,
                                                       False, update, remotes, recorder)

        print_graph(deps_graph, self.app.out)

        # Inject the generators before installing
        for node in deps_graph.nodes:
            if node.recipe == RECIPE_EDITABLE:
                generators = workspace[node.ref].generators
                if generators is not None:
                    tmp = list(node.conanfile.generators)
                    tmp.extend([g for g in generators if g not in tmp])
                    node.conanfile.generators = tmp

        installer = BinaryInstaller(self.app.cache, self.app.out, self.app.remote_manager,
                                    recorder=recorder, hook_manager=self.app.hook_manager)
        installer.install(deps_graph, remotes, keep_build=False, graph_info=graph_info)

        install_folder = install_folder or cwd
        workspace.generate(install_folder, deps_graph, self.app.out)

    @api_method
    def install_reference(self, reference, settings=None, options=None, env=None,
                          remote_name=None, verify=None, manifests=None,
                          manifests_interactive=None, build=None, profile_names=None,
                          update=False, generators=None, install_folder=None, cwd=None,
                          lockfile=None):

        try:
            recorder = ActionRecorder()
            cwd = cwd or os.getcwd()

            manifests = _parse_manifests_arguments(verify, manifests, manifests_interactive, cwd)
            manifest_folder, manifest_interactive, manifest_verify = manifests

            lockfile = _make_abs_path(lockfile, cwd) if lockfile else None
            graph_info = get_graph_info(profile_names, settings, options, env, cwd, None,
                                        self.app.cache, self.app.out, lockfile=lockfile)

            if not generators:  # We don't want the default txt
                generators = False

            install_folder = _make_abs_path(install_folder, cwd)

            mkdir(install_folder)
            remotes = self.app.cache.registry.load_remotes()
            remotes.select(remote_name)
            self.app.python_requires.enable_remotes(update=update, remotes=remotes)
            manager = self._init_manager(recorder)
            manager.install(ref_or_path=reference, install_folder=install_folder,
                            remotes=remotes, graph_info=graph_info, build_modes=build,
                            update=update, manifest_folder=manifest_folder,
                            manifest_verify=manifest_verify,
                            manifest_interactive=manifest_interactive,
                            generators=generators, use_lock=lockfile)
            return recorder.get_info(self.app.cache.config.revisions_enabled)
        except ConanException as exc:
            recorder.error = True
            exc.info = recorder.get_info(self.app.cache.config.revisions_enabled)
            raise

    @api_method
    def install(self, path="", name=None, version=None, user=None, channel=None,
                settings=None, options=None, env=None,
                remote_name=None, verify=None, manifests=None,
                manifests_interactive=None, build=None, profile_names=None,
                update=False, generators=None, no_imports=False, install_folder=None, cwd=None,
                lockfile=None):

        try:
            recorder = ActionRecorder()
            cwd = cwd or os.getcwd()
            manifests = _parse_manifests_arguments(verify, manifests, manifests_interactive, cwd)
            manifest_folder, manifest_interactive, manifest_verify = manifests

            lockfile = _make_abs_path(lockfile, cwd) if lockfile else None
            graph_info = get_graph_info(profile_names, settings, options, env, cwd, None,
                                        self.app.cache, self.app.out,
                                        name=name, version=version, user=user, channel=channel,
                                        lockfile=lockfile)

            install_folder = _make_abs_path(install_folder, cwd)
            conanfile_path = _get_conanfile_path(path, cwd, py=None)

            remotes = self.app.cache.registry.load_remotes()
            remotes.select(remote_name)
            self.app.python_requires.enable_remotes(update=update, remotes=remotes)
            manager = self._init_manager(recorder)
            manager.install(ref_or_path=conanfile_path,
                            install_folder=install_folder,
                            remotes=remotes,
                            graph_info=graph_info,
                            build_modes=build,
                            update=update,
                            manifest_folder=manifest_folder,
                            manifest_verify=manifest_verify,
                            manifest_interactive=manifest_interactive,
                            generators=generators,
                            no_imports=no_imports)
            return recorder.get_info(self.app.cache.config.revisions_enabled)
        except ConanException as exc:
            recorder.error = True
            exc.info = recorder.get_info(self.app.cache.config.revisions_enabled)
            raise

    @api_method
    def config_get(self, item):
        config_parser = ConanClientConfigParser(self.app.cache.conan_conf_path)
        if item == "storage.path":
            result = config_parser.storage_path
        else:
            result = config_parser.get_item(item)
        self.app.out.info(result)
        return result

    @api_method
    def config_set(self, item, value):
        config_parser = ConanClientConfigParser(self.app.cache.conan_conf_path)
        config_parser.set_item(item, value)

    @api_method
    def config_rm(self, item):
        config_parser = ConanClientConfigParser(self.app.cache.conan_conf_path)
        config_parser.rm_item(item)

    @api_method
    def config_install(self, path_or_url, verify_ssl, config_type=None, args=None,
                       source_folder=None, target_folder=None):
        from conans.client.conf.config_installer import configuration_install
        return configuration_install(path_or_url, self.app.cache, self.app.out, verify_ssl,
                                     requester=self.app.requester, config_type=config_type,
                                     args=args,
                                     source_folder=source_folder, target_folder=target_folder)

    def _info_args(self, reference_or_path, install_folder, profile_names, settings, options, env,
                   lockfile=None):
        cwd = get_cwd()
        if check_valid_ref(reference_or_path):
            ref = ConanFileReference.loads(reference_or_path)
            install_folder = _make_abs_path(install_folder, cwd) if install_folder else None
        else:
            ref = _get_conanfile_path(reference_or_path, cwd=None, py=None)

            install_folder = _make_abs_path(install_folder, cwd)
            if not os.path.exists(os.path.join(install_folder, GRAPH_INFO_FILE)):
                install_folder = None

        lockfile = _make_abs_path(lockfile, cwd) if lockfile else None
        graph_info = get_graph_info(profile_names, settings, options, env, cwd, install_folder,
                                    self.app.cache, self.app.out, lockfile=lockfile)

        return ref, graph_info

    @api_method
    def info_build_order(self, reference, settings=None, options=None, env=None,
                         profile_names=None, remote_name=None, build_order=None, check_updates=None,
                         install_folder=None):
        reference, graph_info = self._info_args(reference, install_folder, profile_names,
                                                settings, options, env)
        recorder = ActionRecorder()
        remotes = self.app.cache.registry.load_remotes()
        remotes.select(remote_name)
        self.app.python_requires.enable_remotes(check_updates=check_updates, remotes=remotes)
        deps_graph, _ = self.app.graph_manager.load_graph(reference, None, graph_info, ["missing"],
                                                       check_updates, False, remotes,
                                                       recorder)
        return deps_graph.build_order(build_order)

    @api_method
    def info_nodes_to_build(self, reference, build_modes, settings=None, options=None, env=None,
                            profile_names=None, remote_name=None, check_updates=None,
                            install_folder=None):
        reference, graph_info = self._info_args(reference, install_folder, profile_names,
                                                settings, options, env)
        recorder = ActionRecorder()
        remotes = self.app.cache.registry.load_remotes()
        remotes.select(remote_name)
        self.app.python_requires.enable_remotes(check_updates=check_updates, remotes=remotes)
        deps_graph, conanfile = self.app.graph_manager.load_graph(reference, None, graph_info,
                                                               build_modes, check_updates,
                                                               False, remotes, recorder)
        nodes_to_build = deps_graph.nodes_to_build()
        return nodes_to_build, conanfile

    @api_method
    def info(self, reference_or_path, remote_name=None, settings=None, options=None, env=None,
             profile_names=None, update=False, install_folder=None, build=None, lockfile=None):
        reference, graph_info = self._info_args(reference_or_path, install_folder, profile_names,
                                                settings, options, env, lockfile=lockfile)
        recorder = ActionRecorder()
        remotes = self.app.cache.registry.load_remotes()
        remotes.select(remote_name)
        # FIXME: Using update as check_update?
        self.app.python_requires.enable_remotes(check_updates=update, remotes=remotes)
        deps_graph, conanfile = self.app.graph_manager.load_graph(reference, None, graph_info, build,
                                                               update, False, remotes,
                                                               recorder)

        if install_folder:
            output_folder = _make_abs_path(install_folder)
            graph_info.save(output_folder)
            self.app.out.info("Generated graphinfo")
        return deps_graph, conanfile

    @api_method
    def build(self, conanfile_path, source_folder=None, package_folder=None, build_folder=None,
              install_folder=None, should_configure=True, should_build=True, should_install=True,
              should_test=True, cwd=None):

        remotes = self.app.cache.registry.load_remotes()
        self.app.python_requires.enable_remotes(remotes=remotes)
        cwd = cwd or get_cwd()
        conanfile_path = _get_conanfile_path(conanfile_path, cwd, py=True)
        build_folder = _make_abs_path(build_folder, cwd)
        install_folder = _make_abs_path(install_folder, cwd, default=build_folder)
        source_folder = _make_abs_path(source_folder, cwd, default=os.path.dirname(conanfile_path))
        default_pkg_folder = os.path.join(build_folder, "package")
        package_folder = _make_abs_path(package_folder, cwd, default=default_pkg_folder)

        build(self.app.graph_manager, self.app.hook_manager, conanfile_path,
              source_folder, build_folder, package_folder, install_folder,
              should_configure=should_configure, should_build=should_build,
              should_install=should_install, should_test=should_test)

    @api_method
    def package(self, path, build_folder, package_folder, source_folder=None, install_folder=None,
                cwd=None):
        remotes = self.app.cache.registry.load_remotes()
        self.app.python_requires.enable_remotes(remotes=remotes)

        cwd = cwd or get_cwd()
        conanfile_path = _get_conanfile_path(path, cwd, py=True)
        build_folder = _make_abs_path(build_folder, cwd)
        install_folder = _make_abs_path(install_folder, cwd, default=build_folder)
        source_folder = _make_abs_path(source_folder, cwd, default=os.path.dirname(conanfile_path))
        default_pkg_folder = os.path.join(build_folder, "package")
        package_folder = _make_abs_path(package_folder, cwd, default=default_pkg_folder)

        if package_folder == build_folder:
            raise ConanException("Cannot 'conan package' to the build folder. "
                                 "--build-folder and package folder can't be the same")
        conanfile = self.app.graph_manager.load_consumer_conanfile(conanfile_path, install_folder,
                                                                deps_info_required=True)
        with get_env_context_manager(conanfile):
            packager.create_package(conanfile, None, source_folder, build_folder, package_folder,
                                    install_folder, self.app.hook_manager, conanfile_path, None,
                                    local=True, copy_info=True)

    @api_method
    def source(self, path, source_folder=None, info_folder=None, cwd=None):
        remotes = self.app.cache.registry.load_remotes()
        self.app.python_requires.enable_remotes(remotes=remotes)

        cwd = cwd or get_cwd()
        conanfile_path = _get_conanfile_path(path, cwd, py=True)
        source_folder = _make_abs_path(source_folder, cwd)
        info_folder = _make_abs_path(info_folder, cwd)

        mkdir(source_folder)
        if not os.path.exists(info_folder):
            raise ConanException("Specified info-folder doesn't exist")

        # only infos if exist
        conanfile = self.app.graph_manager.load_consumer_conanfile(conanfile_path, info_folder)
        config_source_local(source_folder, conanfile, conanfile_path, self.app.hook_manager)

    @api_method
    def imports(self, path, dest=None, info_folder=None, cwd=None):
        """
        :param path: Path to the conanfile
        :param dest: Dir to put the imported files. (Abs path or relative to cwd)
        :param info_folder: Dir where the conaninfo.txt and conanbuildinfo.txt files are
        :param cwd: Current working directory
        :return: None
        """
        cwd = cwd or get_cwd()
        info_folder = _make_abs_path(info_folder, cwd)
        dest = _make_abs_path(dest, cwd)

        remotes = self.app.cache.registry.load_remotes()
        self.app.python_requires.enable_remotes(remotes=remotes)
        mkdir(dest)
        conanfile_abs_path = _get_conanfile_path(path, cwd, py=None)
        conanfile = self.app.graph_manager.load_consumer_conanfile(conanfile_abs_path, info_folder,
                                                                deps_info_required=True)
        run_imports(conanfile, dest)

    @api_method
    def imports_undo(self, manifest_path):
        cwd = get_cwd()
        manifest_path = _make_abs_path(manifest_path, cwd)
        undo_imports(manifest_path, self.app.out)

    @api_method
    def export(self, path, name, version, user, channel, keep_source=False, cwd=None,
               lockfile=None):
        conanfile_path = _get_conanfile_path(path, cwd, py=True)
        graph_lock = None
        if lockfile:
            lockfile = _make_abs_path(lockfile, cwd)
            graph_lock_file = GraphLockFile.load(lockfile)
            graph_lock = graph_lock_file.graph_lock
            self.app.out.info("Using lockfile: '{}'".format(lockfile))

        remotes = self.app.cache.registry.load_remotes()
        self.app.python_requires.enable_remotes(remotes=remotes)
        cmd_export(conanfile_path, name, version, user, channel, keep_source,
                   self.app.cache.config.revisions_enabled, self.app.out,
                   self.app.hook_manager, self.app.loader, self.app.cache, graph_lock=graph_lock)

        if lockfile:
            graph_lock_file.save(lockfile)

    @api_method
    def remove(self, pattern, query=None, packages=None, builds=None, src=False, force=False,
               remote_name=None, outdated=False):
        remotes = self.app.cache.registry.load_remotes()
        remover = ConanRemover(self.app.cache, self.app.remote_manager, self.user_io, remotes)
        remover.remove(pattern, remote_name, src, builds, packages, force=force,
                       packages_query=query, outdated=outdated)

    @api_method
    def copy(self, reference, user_channel, force=False, packages=None):
        """
        param packages: None=No binaries, True=All binaries, else list of IDs
        """
        from conans.client.cmd.copy import cmd_copy
        remotes = self.app.cache.registry.load_remotes()
        self.app.python_requires.enable_remotes(remotes=remotes)
        # FIXME: conan copy does not support short-paths in Windows
        ref = ConanFileReference.loads(reference)
        cmd_copy(ref, user_channel, packages, self.app.cache,
                 self.user_io, self.app.remote_manager, self.app.loader, remotes, force=force)

    @api_method
    def authenticate(self, name, password, remote_name, skip_auth=False):
        # FIXME: 2.0 rename "name" to "user".
        # FIXME: 2.0 probably we should return also if we have been authenticated or not (skipped)
        # FIXME: 2.0 remove the skip_auth argument, that behavior will be done by:
        #      "conan user USERNAME -r remote" that will use the local credentials (
        #      and verify that are valid)
        #      against the server. Currently it only "associate" the USERNAME with the remote
        #      without checking anything else
        remote = self.get_remote_by_name(remote_name)

        if skip_auth and token_present(self.app.cache.localdb, remote, name):
            return remote.name, name, name
        if not password:
            name, password = self.user_io.request_login(remote_name=remote_name, username=name)

        _, remote_name, prev_user, user = self.app.remote_manager.authenticate(remote, name,
                                                                               password)
        return remote_name, prev_user, user

    @api_method
    def user_set(self, user, remote_name=None):
        remote = (self.get_default_remote() if not remote_name
                  else self.get_remote_by_name(remote_name))
        return user_set(self.app.cache.localdb, user, remote)

    @api_method
    def users_clean(self):
        users_clean(self.app.cache.localdb)

    @api_method
    def users_list(self, remote_name=None):
        info = {"error": False, "remotes": []}
        remotes = [self.get_remote_by_name(remote_name)] if remote_name else self.remote_list()
        try:
            info["remotes"] = users_list(self.app.cache.localdb, remotes)
            return info
        except ConanException as exc:
            info["error"] = True
            exc.info = info
            raise

    @api_method
    def search_recipes(self, pattern, remote_name=None, case_sensitive=False,
                       fill_revisions=False):
        search_recorder = SearchRecorder()
        remotes = self.app.cache.registry.load_remotes()
        search = Search(self.app.cache, self.app.remote_manager, remotes)

        try:
            references = search.search_recipes(pattern, remote_name, case_sensitive)
        except ConanException as exc:
            search_recorder.error = True
            exc.info = search_recorder.get_info()
            raise

        for remote_name, refs in references.items():
            for ref in refs:
                if fill_revisions:
                    layout = self.app.cache.package_layout(ref)
                    if isinstance(layout, PackageCacheLayout):
                        ref = ref.copy_with_rev(layout.recipe_revision())

                search_recorder.add_recipe(remote_name, ref, with_packages=False)
        return search_recorder.get_info()

    @api_method
    def search_packages(self, reference, query=None, remote_name=None, outdated=False):
        search_recorder = SearchRecorder()
        remotes = self.app.cache.registry.load_remotes()
        search = Search(self.app.cache, self.app.remote_manager, remotes)

        try:
            ref = ConanFileReference.loads(reference)
            references = search.search_packages(ref, remote_name, query=query, outdated=outdated)
        except ConanException as exc:
            search_recorder.error = True
            exc.info = search_recorder.get_info()
            raise

        for remote_name, remote_ref in references.items():
            search_recorder.add_recipe(remote_name, ref)
            if remote_ref.ordered_packages:
                for package_id, properties in remote_ref.ordered_packages.items():
                    package_recipe_hash = properties.get("recipe_hash", None)
                    search_recorder.add_package(remote_name, ref,
                                                package_id, properties.get("options", []),
                                                properties.get("settings", []),
                                                properties.get("full_requires", []),
                                                remote_ref.recipe_hash != package_recipe_hash)
        return search_recorder.get_info()

    @api_method
    def upload(self, pattern, package=None, remote_name=None, all_packages=False, confirm=False,
               retry=None, retry_wait=None, integrity_check=False, policy=None, query=None):
        """ Uploads a package recipe and the generated binary packages to a specified remote
        """
        upload_recorder = UploadRecorder()
        uploader = CmdUpload(self.app.cache, self.user_io, self.app.remote_manager,
                             self.app.loader, self.app.hook_manager)
        remotes = self.app.cache.registry.load_remotes()
        remotes.select(remote_name)
        self.app.python_requires.enable_remotes(remotes=remotes)
        try:
            uploader.upload(pattern, remotes, upload_recorder, package, all_packages, confirm,
                            retry, retry_wait, integrity_check, policy, query=query)
            return upload_recorder.get_info()
        except ConanException as exc:
            upload_recorder.error = True
            exc.info = upload_recorder.get_info()
            raise

    @api_method
    def remote_list(self):
        return list(self.app.cache.registry.load_remotes().values())

    @api_method
    def remote_add(self, remote_name, url, verify_ssl=True, insert=None, force=None):
        return self.app.cache.registry.add(remote_name, url, verify_ssl, insert, force)

    @api_method
    def remote_remove(self, remote_name):
        return self.app.cache.registry.remove(remote_name)

    @api_method
    def remote_update(self, remote_name, url, verify_ssl=True, insert=None):
        return self.app.cache.registry.update(remote_name, url, verify_ssl, insert)

    @api_method
    def remote_rename(self, remote_name, new_new_remote):
        return self.app.cache.registry.rename(remote_name, new_new_remote)

    @api_method
    def remote_list_ref(self):
        return {str(r): remote_name for r, remote_name in self.app.cache.registry.refs_list.items()
                if remote_name}

    @api_method
    def remote_add_ref(self, reference, remote_name):
        ref = ConanFileReference.loads(reference, validate=True)
        remote = self.app.cache.registry.load_remotes()[remote_name]
        with self.app.cache.package_layout(ref).update_metadata() as metadata:
            metadata.recipe.remote = remote.name

    @api_method
    def remote_remove_ref(self, reference):
        ref = ConanFileReference.loads(reference, validate=True)
        with self.app.cache.package_layout(ref).update_metadata() as metadata:
            metadata.recipe.remote = None

    @api_method
    def remote_update_ref(self, reference, remote_name):
        ref = ConanFileReference.loads(reference, validate=True)
        remote = self.app.cache.registry.load_remotes()[remote_name]
        with self.app.cache.package_layout(ref).update_metadata() as metadata:
            metadata.recipe.remote = remote.name

    @api_method
    def remote_list_pref(self, reference):
        ref = ConanFileReference.loads(reference, validate=True)
        ret = {}
        tmp = self.app.cache.registry.prefs_list
        for pref, remote in tmp.items():
            if pref.ref == ref and remote:
                ret[repr(pref)] = remote
        return ret

    @api_method
    def remote_add_pref(self, package_reference, remote_name):
        pref = PackageReference.loads(package_reference, validate=True)
        remote = self.app.cache.registry.load_remotes()[remote_name]
        with self.app.cache.package_layout(pref.ref).update_metadata() as metadata:
            m = metadata.packages.get(pref.id)
            if m and m.remote:
                raise ConanException("%s already exists. Use update" % str(pref))
            metadata.packages[pref.id].remote = remote.name

    @api_method
    def remote_remove_pref(self, package_reference):
        pref = PackageReference.loads(package_reference, validate=True)
        with self.app.cache.package_layout(pref.ref).update_metadata() as metadata:
            m = metadata.packages.get(pref.id)
            if m:
                m.remote = None

    @api_method
    def remote_update_pref(self, package_reference, remote_name):
        pref = PackageReference.loads(package_reference, validate=True)
        self.app.cache.registry.load_remotes()[remote_name]
        with self.app.cache.package_layout(pref.ref).update_metadata() as metadata:
            m = metadata.packages.get(pref.id)
            if m:
                m.remote = remote_name

    @api_method
    def remote_clean(self):
        return self.app.cache.registry.clear()

    @api_method
    def remove_system_reqs(self, reference):
        try:
            ref = ConanFileReference.loads(reference)
            self.app.cache.package_layout(ref).remove_system_reqs()
            self.app.out.info(
                "Cache system_reqs from %s has been removed" % repr(ref))
        except Exception as error:
            raise ConanException("Unable to remove system_reqs: %s" % error)

    @api_method
    def remove_system_reqs_by_pattern(self, pattern):
        for ref in search_recipes(self.app.cache, pattern=pattern):
            self.remove_system_reqs(repr(ref))

    @api_method
    def remove_locks(self):
        self.app.cache.remove_locks()

    @api_method
    def profile_list(self):
        return cmd_profile_list(self.app.cache.profiles_path, self.app.out)

    @api_method
    def create_profile(self, profile_name, detect=False, force=False):
        return cmd_profile_create(profile_name, self.app.cache.profiles_path,
                                  self.app.out, detect, force)

    @api_method
    def update_profile(self, profile_name, key, value):
        return cmd_profile_update(profile_name, key, value, self.app.cache.profiles_path)

    @api_method
    def get_profile_key(self, profile_name, key):
        return cmd_profile_get(profile_name, key, self.app.cache.profiles_path)

    @api_method
    def delete_profile_key(self, profile_name, key):
        return cmd_profile_delete_key(profile_name, key, self.app.cache.profiles_path)

    @api_method
    def read_profile(self, profile=None):
        p, _ = read_profile(profile, get_cwd(), self.app.cache.profiles_path)
        return p

    @api_method
    def get_path(self, reference, package_id=None, path=None, remote_name=None):
        ref = ConanFileReference.loads(reference)
        if not path:
            path = "conanfile.py" if not package_id else "conaninfo.txt"

        if not remote_name:
            package_layout = self.app.cache.package_layout(ref, short_paths=None)
            return package_layout.get_path(path=path, package_id=package_id), path
        else:
            remote = self.get_remote_by_name(remote_name)
            if self.app.cache.config.revisions_enabled and not ref.revision:
                ref = self.app.remote_manager.get_latest_recipe_revision(ref, remote)
            if package_id:
                pref = PackageReference(ref, package_id)
                if self.app.cache.config.revisions_enabled and not pref.revision:
                    pref = self.app.remote_manager.get_latest_package_revision(pref, remote)
                return self.app.remote_manager.get_package_path(pref, path, remote), path
            else:
                return self.app.remote_manager.get_recipe_path(ref, path, remote), path

    @api_method
    def export_alias(self, reference, target_reference):
        ref = ConanFileReference.loads(reference)
        target_ref = ConanFileReference.loads(target_reference)

        if ref.name != target_ref.name:
            raise ConanException("An alias can only be defined to a package with the same name")

        # Do not allow to override an existing package
        alias_conanfile_path = self.app.cache.package_layout(ref).conanfile()
        if os.path.exists(alias_conanfile_path):
            conanfile_class = self.app.loader.load_class(alias_conanfile_path)
            conanfile = conanfile_class(self.app.out, None, repr(ref))
            if not getattr(conanfile, 'alias', None):
                raise ConanException("Reference '{}' is already a package, remove it before "
                                     "creating and alias with the same name".format(ref))

        package_layout = self.app.cache.package_layout(ref)
        return export_alias(package_layout, target_ref,
                            revisions_enabled=self.app.cache.config.revisions_enabled,
                            output=self.app.out)

    @api_method
    def get_default_remote(self):
        return self.app.cache.registry.load_remotes().default

    @api_method
    def get_remote_by_name(self, remote_name):
        return self.app.cache.registry.load_remotes()[remote_name]

    @api_method
    def get_recipe_revisions(self, reference, remote_name=None):
        if not self.app.cache.config.revisions_enabled:
            raise ConanException("The client doesn't have the revisions feature enabled."
                                 " Enable this feature setting to '1' the environment variable"
                                 " 'CONAN_REVISIONS_ENABLED' or the config value"
                                 " 'general.revisions_enabled' in your conan.conf file")
        ref = ConanFileReference.loads(reference)
        if ref.revision:
            raise ConanException("Cannot list the revisions of a specific recipe revision")

        if not remote_name:
            layout = self.app.cache.package_layout(ref)
            try:
                rev = layout.recipe_revision()
            except RecipeNotFoundException as e:
                e.print_rev = True
                raise e

            # Check the time in the associated remote if any
            remote_name = layout.load_metadata().recipe.remote
            remote = self.app.cache.registry.load_remotes()[remote_name] if remote_name else None
            rev_time = None
            if remote:
                try:
                    revisions = self.app.remote_manager.get_recipe_revisions(ref, remote)
                except RecipeNotFoundException:
                    pass
                except (NoRestV2Available, NotFoundException):
                    rev_time = None
                else:
                    tmp = {r["revision"]: r["time"] for r in revisions}
                    rev_time = tmp.get(rev)

            return [{"revision": rev, "time": rev_time}]
        else:
            remote = self.get_remote_by_name(remote_name)
            return self.app.remote_manager.get_recipe_revisions(ref, remote=remote)

    @api_method
    def get_package_revisions(self, reference, remote_name=None):
        if not self.app.cache.config.revisions_enabled:
            raise ConanException("The client doesn't have the revisions feature enabled."
                                 " Enable this feature setting to '1' the environment variable"
                                 " 'CONAN_REVISIONS_ENABLED' or the config value"
                                 " 'general.revisions_enabled' in your conan.conf file")
        pref = PackageReference.loads(reference, validate=True)
        if not pref.ref.revision:
            raise ConanException("Specify a recipe reference with revision")
        if pref.revision:
            raise ConanException("Cannot list the revisions of a specific package revision")

        if not remote_name:
            layout = self.app.cache.package_layout(pref.ref)
            try:
                rev = layout.package_revision(pref)
            except (RecipeNotFoundException, PackageNotFoundException) as e:
                e.print_rev = True
                raise e

            # Check the time in the associated remote if any
            remote_name = layout.load_metadata().recipe.remote
            remote = self.app.cache.registry.load_remotes()[remote_name] if remote_name else None
            rev_time = None
            if remote:
                try:
                    revisions = self.app.remote_manager.get_package_revisions(pref, remote)
                except RecipeNotFoundException:
                    pass
                except (NoRestV2Available, NotFoundException):
                    rev_time = None
                else:
                    tmp = {r["revision"]: r["time"] for r in revisions}
                    rev_time = tmp.get(rev)

            return [{"revision": rev, "time": rev_time}]
        else:
            remote = self.get_remote_by_name(remote_name)
            return self.app.remote_manager.get_package_revisions(pref, remote=remote)

    @api_method
    def editable_add(self, path, reference, layout, cwd):
        # Retrieve conanfile.py from target_path
        target_path = _get_conanfile_path(path=path, cwd=cwd, py=True)

        remotes = self.app.cache.registry.load_remotes()
        self.app.python_requires.enable_remotes(remotes=remotes)

        # Check the conanfile is there, and name/version matches
        ref = ConanFileReference.loads(reference, validate=True)
        target_conanfile = self.app.graph_manager._loader.load_class(target_path)
        if (target_conanfile.name and target_conanfile.name != ref.name) or \
                (target_conanfile.version and target_conanfile.version != ref.version):
            raise ConanException("Name and version from reference ({}) and target "
                                 "conanfile.py ({}/{}) must match".
                                 format(ref, target_conanfile.name, target_conanfile.version))

        layout_abs_path = get_editable_abs_path(layout, cwd, self.app.cache.cache_folder)
        if layout_abs_path:
            self.app.out.success("Using layout file: %s" % layout_abs_path)
        self.app.cache.editable_packages.add(ref, os.path.dirname(target_path), layout_abs_path)

    @api_method
    def editable_remove(self, reference):
        ref = ConanFileReference.loads(reference, validate=True)
        return self.app.cache.editable_packages.remove(ref)

    @api_method
    def editable_list(self):
        return {str(k): v for k, v in self.app.cache.editable_packages.edited_refs.items()}

    @api_method
    def update_lock(self, old_lockfile, new_lockfile, cwd=None):
        cwd = cwd or os.getcwd()
        old_lockfile = _make_abs_path(old_lockfile, cwd)
        old_lock = GraphLockFile.load(old_lockfile)
        new_lockfile = _make_abs_path(new_lockfile, cwd)
        new_lock = GraphLockFile.load(new_lockfile)
        if old_lock.profile.dumps() != new_lock.profile.dumps():
            raise ConanException("Profiles of lockfiles are different\n%s:\n%s\n%s:\n%s"
                                 % (old_lockfile, old_lock.profile.dumps(),
                                    new_lockfile, new_lock.profile.dumps()))
        old_lock.graph_lock.update_lock(new_lock.graph_lock)
        old_lock.save(old_lockfile)

    @api_method
    def build_order(self, lockfile, build=None, cwd=None):
        cwd = cwd or os.getcwd()
        lockfile = _make_abs_path(lockfile, cwd)

        recorder = ActionRecorder()
        remotes = self.app.cache.registry.load_remotes()
        self.app.python_requires.enable_remotes(remotes=remotes)

        graph_info = get_graph_info(None, None, None, None,
                                    cwd=cwd, install_folder=None,
                                    cache=self.app.cache, output=self.app.out,
                                    lockfile=lockfile)
        reference = graph_info.graph_lock.root_node().pref.ref.copy_clear_rev()
        deps_graph, _ = self.app.graph_manager.load_graph(reference, None, graph_info, build,
                                                       False, False, remotes, recorder)

        print_graph(deps_graph, self.app.out)
        graph_info.save_lock(lockfile)
        return deps_graph.new_build_order()

    @api_method
    def create_lock(self, reference, remote_name=None, settings=None, options=None, env=None,
                    profile_names=None, update=False, lockfile=None, build=None,):
        reference, graph_info = self._info_args(reference, None, profile_names,
                                                settings, options, env)
        recorder = ActionRecorder()
        remotes = self.app.cache.registry.load_remotes()
        remotes.select(remote_name)
        # FIXME: Using update as check_update?
        self.app.python_requires.enable_remotes(check_updates=update, remotes=remotes)
        deps_graph, _ = self.app.graph_manager.load_graph(reference, None, graph_info, build, update,
                                                       False, remotes, recorder)

        print_graph(deps_graph, self.app.out)
        lockfile = _make_abs_path(lockfile)
        graph_info.save_lock(lockfile)
        self.app.out.info("Generated lockfile")


Conan = ConanAPIV1


def get_graph_info(profile_names, settings, options, env, cwd, install_folder, cache, output,
                   name=None, version=None, user=None, channel=None, lockfile=None):
    if lockfile:
        try:
            graph_info_folder = lockfile if os.path.isdir(lockfile) else os.path.dirname(lockfile)
            graph_info = GraphInfo.load(graph_info_folder)
        except IOError:  # Only if file is missing
            graph_info = GraphInfo()
            root_ref = ConanFileReference(name, version, user, channel, validate=False)
            graph_info.root = root_ref
        lockfile = lockfile if os.path.isfile(lockfile) else os.path.join(lockfile, LOCKFILE)
        graph_lock_file = GraphLockFile.load(lockfile)
        graph_info.profile = graph_lock_file.profile
        graph_info.profile.process_settings(cache, preprocess=False)
        graph_info.graph_lock = graph_lock_file.graph_lock
        output.info("Using lockfile: '{}'".format(lockfile))
        return graph_info

    try:
        graph_info = GraphInfo.load(install_folder)
    except IOError:  # Only if file is missing
        if install_folder:
            raise ConanException("Failed to load graphinfo file in install-folder: %s"
                                 % install_folder)
        graph_info = None
    else:
        graph_lock_file = GraphLockFile.load(install_folder)
        graph_info.profile = graph_lock_file.profile
        graph_info.profile.process_settings(cache, preprocess=False)

    if profile_names or settings or options or env or not graph_info:
        if graph_info:
            # FIXME: Convert to Exception in Conan 2.0
            output.warn("Settings, options, env or profile specified. "
                        "GraphInfo found from previous install won't be used: %s\n"
                        "Don't pass settings, options or profile arguments if you want to reuse "
                        "the installed graph-info file."
                        % install_folder)

        profile = profile_from_args(profile_names, settings, options, env, cwd, cache)
        profile.process_settings(cache)
        root_ref = ConanFileReference(name, version, user, channel, validate=False)
        graph_info = GraphInfo(profile=profile, root_ref=root_ref)
        # Preprocess settings and convert to real settings
    return graph_info


def _parse_manifests_arguments(verify, manifests, manifests_interactive, cwd):
    if manifests and manifests_interactive:
        raise ConanException("Do not specify both manifests and "
                             "manifests-interactive arguments")
    if verify and (manifests or manifests_interactive):
        raise ConanException("Do not specify both 'verify' and "
                             "'manifests' or 'manifests-interactive' arguments")
    manifest_folder = verify or manifests or manifests_interactive
    if manifest_folder:
        if not os.path.isabs(manifest_folder):
            if not cwd:
                raise ConanException("'cwd' should be defined if the manifest folder is relative.")
            manifest_folder = os.path.join(cwd, manifest_folder)
        manifest_verify = verify is not None
        manifest_interactive = manifests_interactive is not None
    else:
        manifest_verify = manifest_interactive = False

    return manifest_folder, manifest_interactive, manifest_verify


def existing_info_files(folder):
    return os.path.exists(os.path.join(folder, CONANINFO)) and  \
           os.path.exists(os.path.join(folder, BUILD_INFO))
