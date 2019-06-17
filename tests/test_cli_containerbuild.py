"""
Copyright (C) 2019  Red Hat, Inc.

This library is free software; you can redistribute it and/or
modify it under the terms of the GNU Lesser General Public
License as published by the Free Software Foundation; either
version 2.1 of the License, or (at your option) any later version.

This library is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
Lesser General Public License for more details.

You should have received a copy of the GNU Lesser General Public
License along with this library; if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA
"""

import pytest
from flexmock import flexmock
from collections import OrderedDict

from koji_containerbuild.plugins import cli_containerbuild
from koji_containerbuild.plugins.cli_containerbuild import parse_arguments


def mock_session(target,
                 source,
                 target_known=True,
                 dest_tag_name='destination',
                 dest_tag_known=True,
                 dest_tag_locked=False,
                 task_id='42',
                 task_success=True,
                 task_result={},
                 priority=None,
                 channel=cli_containerbuild.DEFAULT_CHANNEL,
                 running_in_background=False):
    """
    Mock a session for the purposes of cli_containerbuild.handle_build()

    The default argument values are set up for a successful build,
    as long as `target` and `source` match those provided via CLI args.
    """
    (flexmock(cli_containerbuild)
        .should_receive('activate_session'))  # and do nothing
    (flexmock(cli_containerbuild)
        .should_receive('_running_in_bg')
        .and_return(running_in_background))
    (flexmock(cli_containerbuild)
        .should_receive('watch_tasks')
        .and_return(0 if task_success else 1))

    build_target = {'dest_tag': dest_tag_name,
                    'dest_tag_name': dest_tag_name}

    dest_tag = {'name': dest_tag_name,
                'locked': dest_tag_locked}

    session_status = {'logged_in': True}

    def logout():
        session_status['logged_in'] = False

    session = flexmock(status=session_status, logout=logout)
    (session
        .should_receive('getBuildTarget')
        .with_args(target)
        .and_return(build_target if target_known else None))
    (session
        .should_receive('getTag')
        .with_args(build_target['dest_tag'])
        .and_return(dest_tag if dest_tag_known else None))
    (session
        .should_receive('buildContainer')
        .with_args(source, target, dict,
                   priority=priority, channel=channel)
        .and_return(task_id))
    (session
        .should_receive('getTaskResult')
        .with_args(task_id)
        .and_return(task_result))

    return session


def build_cli_args(target,
                   source,
                   git_branch='random-branch',
                   wait=None,
                   background=False):
    """Build command line arguments for cli_containerbuild.handle_build()"""
    args = [target, source, '--git-branch', git_branch]
    if wait is not None:
        args.append('--wait' if wait else '--nowait')
    if background:
        args.append('--background')
    return args


def _expected_output(result, offset, indent):
    if isinstance(result, list):
        for item in result:
            for line in _expected_output(item, offset+indent, indent):
                yield line
    elif isinstance(result, dict):
        for key, value in result.items():
            yield '{}{}:\n'.format(offset, key)
            for line in _expected_output(value, offset+indent, indent):
                yield line
    else:
        yield '{}{}\n'.format(offset, result)


def expected_task_output(task_id, result, weburl, quiet=False):
    result['koji_builds'] = ['{}/buildinfo?buildID={}'.format(weburl, build_id)
                             for build_id in result.get('koji_builds', [])]
    output = ''
    if not quiet:
        output += 'Created task: {}\n'.format(task_id)
        output += 'Task info: {}/taskinfo?taskID={}\n'.format(weburl, task_id)
    output += "Task Result ({}):\n".format(task_id)
    output += ''.join(_expected_output(result, offset='', indent=' ' * 2))
    return output


def make_dicts_ordered(obj):
    """Make dicts in a json-like object ordered"""
    if isinstance(obj, dict):
        obj = OrderedDict(obj)
        for k, v in obj.items():
            obj[k] = make_dicts_ordered(v)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            obj[i] = make_dicts_ordered(v)
    return obj


class TestCLI(object):
    """Tests for the cli_containerbuild plugin"""

    # split into multiple groups to minimize run time and complexity
    @pytest.mark.parametrize(('wait', 'quiet'), (
        (None, None),
        (True, None),
        (None, True),
        (None, False),
        (True, True),
    ))
    @pytest.mark.parametrize(('epoch', 'repo_url', 'git_branch',
                              'channel_override', 'compose_ids', 'signing_intent'), (
        (None, None, 'master', None, None, None),
        ('Tuesday', None, 'master', None, None, None),
        (None, ['http://test'], 'master', None, None, None),
        (None, ['http://test1', 'http://test2'], 'master', None, None, None),
        (None, None, 'stable', None, None, None),
        (None, None, 'master', 'override', None, None),
        (None, None, 'master', None, [1], None),
        (None, None, 'master', None, [1, 2], None),
        (None, None, 'master', None, None, 'intent1'),
        ('Tuesday', ['http://test1', 'http://test2'],
         'stable', 'override', None, None),
    ))
    @pytest.mark.parametrize(('scratch', 'isolated', 'koji_parent_build',
                              'release', 'flatpak'), (
        (None, None, None, None, None),
        (None, None, None, 'test-release', None),
        (None, True, None, None, None),
        (None, True, None, 'test-release', None),
        (None, True, 'parent_build', None, None),
        (None, False, None, None, True),
        (True, False, None, None, True),
        (True, None, None, None, None),
        (True, None, 'parent_build', None, None),
    ))
    def test_cli_args(self, tmpdir, scratch, wait, quiet,
                      epoch, repo_url, git_branch, channel_override, release,
                      isolated, koji_parent_build, flatpak, compose_ids,
                      signing_intent):
        options = flexmock(allowed_scms='pkgs.example.com:/*:no')
        options.quiet = False
        test_args = ['test', 'test']
        expected_args = ['test', 'test']
        expected_opts = {}

        if scratch:
            test_args.append('--scratch')
            expected_opts['scratch'] = scratch

        if wait:
            test_args.append('--wait')
        elif wait is False:
            test_args.append('--nowait')

        if quiet:
            test_args.append('--quiet')

        if epoch:
            test_args.append('--epoch')
            test_args.append(epoch)
            expected_opts['epoch'] = epoch

        if repo_url:
            expected_opts['yum_repourls'] = []
            for url in repo_url:
                test_args.append('--repo-url')
                test_args.append(url)
                expected_opts['yum_repourls'].append(url)

        if git_branch:
            test_args.append('--git-branch')
            test_args.append(git_branch)
            expected_opts['git_branch'] = git_branch

        if channel_override:
            test_args.append('--channel-override')
            test_args.append(channel_override)

        if release:
            test_args.append('--release')
            test_args.append(release)
            expected_opts['release'] = release

        if koji_parent_build:
            test_args.append('--koji-parent-build')
            test_args.append(koji_parent_build)
            expected_opts['koji_parent_build'] = koji_parent_build

        if isolated:
            test_args.append('--isolated')
            expected_opts['isolated'] = isolated

        if flatpak:
            expected_opts['flatpak'] = flatpak

        if compose_ids:
            expected_opts['compose_ids'] = []
            for cid in compose_ids:
                test_args.append('--compose-id')
                test_args.append(str(cid))
                expected_opts['compose_ids'].append(cid)

        if signing_intent:
            test_args.append('--signing-intent')
            test_args.append(signing_intent)
            expected_opts['signing_intent'] = signing_intent

        build_opts, parsed_args, opts, _ = parse_arguments(options, test_args, flatpak=flatpak)
        expected_quiet = quiet or options.quiet
        expected_channel = channel_override or 'container'

        assert build_opts.scratch == scratch
        assert build_opts.wait == wait
        assert build_opts.quiet == expected_quiet
        assert build_opts.epoch == epoch
        assert build_opts.yum_repourls == repo_url
        assert build_opts.git_branch == git_branch
        assert build_opts.channel_override == expected_channel
        if not flatpak:
            assert build_opts.release == release
        assert build_opts.compose_ids == compose_ids
        assert build_opts.signing_intent == signing_intent

        assert parsed_args == expected_args
        assert opts == expected_opts

    @pytest.mark.parametrize(('scratch', 'arch_override', 'valid'), (
        (True, 'x86_64', True),
        (True, 'x86_64,ppc64le', True),
        (True, 'x86_64 ppc64le', True),
        (False, 'x86_64', False),
        (False, 'x86_64,ppc64le', False),
        (False, 'x86_64 ppc64le', False),
    ))
    def test_arch_override_restriction(self, tmpdir, scratch, arch_override, valid):
        options = flexmock(allowed_scms='pkgs.example.com:/*:no')
        options.quiet = False
        test_args = ['test', 'test', '--git-branch', 'the-branch']
        expected_args = ['test', 'test']
        expected_opts = {'git_branch': 'the-branch'}

        if scratch:
            test_args.append('--scratch')
            expected_opts['scratch'] = scratch

        if arch_override:
            test_args.append('--arch-override')
            test_args.append(arch_override)
            expected_opts['arch_override'] = arch_override.replace(',', ' ')

        if not valid:
            with pytest.raises(SystemExit):
                parse_arguments(options, test_args, flatpak=False)
            return

        build_opts, parsed_args, opts, _ = parse_arguments(options, test_args, flatpak=False)

        assert build_opts.scratch == scratch
        assert build_opts.arch_override == arch_override

        assert parsed_args == expected_args
        assert opts == expected_opts

    @pytest.mark.parametrize(('scratch', 'isolated', 'valid'), (
        (True, True, False),
        (True, None, True),
        (None, None, True),
        (None, True, True),
    ))
    def test_isolated_scratch_restriction(self, tmpdir, scratch, isolated, valid):
        options = flexmock(allowed_scms='pkgs.example.com:/*:no')
        options.quiet = False
        test_args = ['test', 'test', '--git-branch', 'the-branch']
        expected_args = ['test', 'test']
        expected_opts = {'git_branch': 'the-branch'}
        release = '20.1'

        if scratch:
            test_args.append('--scratch')
            expected_opts['scratch'] = scratch

        if isolated:
            test_args.append('--isolated')
            expected_opts['isolated'] = isolated

            test_args.append('--release')
            test_args.append(release)
            expected_opts['release'] = release

        if not valid:
            with pytest.raises(SystemExit):
                parse_arguments(options, test_args, flatpak=False)
            return

        build_opts, parsed_args, opts, _ = parse_arguments(options, test_args, flatpak=False)

        assert build_opts.scratch == scratch
        assert build_opts.isolated == isolated

        assert parsed_args == expected_args
        assert opts == expected_opts

    @pytest.mark.parametrize((
        'compose_ids', 'signing_intent', 'yum_repourls', 'valid'
    ), (
        (None, None, None, True),
        ([1, 2, 3], None, None, True),
        (None, 'intent1', None, True),
        (None, None, ['www.repo.com'], True),
        ([1, 2, 3], 'intent1', None, False),
        ([1, 2, 3], None, ['www.repo.com'], True),
        ([1, 2, 3], 'intent1', ['www.repo.com'], False),
    ))
    def test_compose_id_arg_restrictions(self, tmpdir, compose_ids, signing_intent, yum_repourls,
                                         valid):
        options = flexmock(allowed_scms='pkgs.example.com:/*:no')
        options.quiet = False
        test_args = ['test', 'test', '--git-branch', 'the-branch']
        expected_args = ['test', 'test']
        expected_opts = {'git_branch': 'the-branch'}

        if compose_ids:
            for ci in compose_ids:
                test_args.append('--compose-id')
                test_args.append(str(ci))
            expected_opts['compose_ids'] = compose_ids

        if signing_intent:
            test_args.append('--signing-intent')
            test_args.append(signing_intent)
            expected_opts['signing_intent'] = signing_intent

        if yum_repourls:
            for yru in yum_repourls:
                test_args.append('--repo-url')
                test_args.append(yru)
            expected_opts['yum_repourls'] = yum_repourls

        if not valid:
            with pytest.raises(SystemExit):
                parse_arguments(options, test_args, flatpak=False)
            return

        build_opts, parsed_args, opts, _ = parse_arguments(options, test_args, flatpak=False)

        assert build_opts.compose_ids == compose_ids
        assert build_opts.signing_intent == signing_intent
        assert build_opts.yum_repourls == yum_repourls

        assert parsed_args == expected_args
        assert opts == expected_opts

    @pytest.mark.parametrize('cause, stderr_msg', [
        ('unknown target', 'Unknown build target'),
        ('unknown dest tag', 'Unknown destination tag'),
        ('dest tag locked', 'is locked'),
        (':// not in URL', 'scm URL does not look like an URL to a source repository'),
        ('# not in URL', 'scm URL must be of the form <url_to_repository>#<revision>)')
    ])
    def test_build_sysexit(self, cause, stderr_msg, capsys):
        target = 'target'
        source = 'https://repo#revision'
        if cause == ':// not in URL':
            source = source.replace('://', '')
        elif cause == '# not in URL':
            source = source.replace('#', '')

        options = flexmock(quiet=True)

        session = mock_session(
            target,
            source,
            target_known=(cause != 'unknown target'),
            dest_tag_known=(cause != 'unknown dest tag'),
            dest_tag_locked=(cause == 'dest tag locked')
        )

        args = build_cli_args(target, source)

        with pytest.raises(SystemExit):
            cli_containerbuild.handle_container_build(options, session, args)

        _, stderr_output = capsys.readouterr()
        assert stderr_msg in stderr_output

    @pytest.mark.parametrize('flatpak', [True, False])
    @pytest.mark.parametrize('quiet', [True, False])
    @pytest.mark.parametrize('build_result', [
        {},
        {'empty_list': []},
        {'empty_dict': {}},
        {'list': ['item_1', 'item_2'],
         'dict': {'key': 'value'},
         'key': 'value'},
        {'list_of_dicts': [
            {},
            {'key': 'value'},
            {'sublist': ['item']},
            {'subdict': {'inner_key': 'inner_value'}}
        ]},
        {'list_of_lists': [
            [],
            ['item_1', 'item_2'],
            [['nested']],
            ['various_types', {'key': 'value'}]
        ]}
    ])
    def test_build_success(self, build_result, quiet, flatpak, capsys):
        target = 'target'
        source = 'https://repo#revision'
        task_id = '42'
        # to prevent test failures due to dict iteration randomness
        build_result = make_dicts_ordered(build_result)

        options = flexmock(quiet=quiet, weburl='x.org')

        session = mock_session(
            target,
            source,
            task_id=task_id,
            task_result=build_result
        )

        args = build_cli_args(target, source)
        handle_build = (cli_containerbuild.handle_flatpak_build if flatpak
                        else cli_containerbuild.handle_container_build)

        rv = handle_build(options, session, args)
        stdout_output, _ = capsys.readouterr()

        expected_output = expected_task_output(task_id, build_result,
                                               options.weburl, quiet=quiet)

        assert rv == 0
        assert stdout_output == expected_output
        assert not session.status['logged_in']

    def test_build_failure(self, capsys):
        target = 'target'
        source = 'https://repo#revision'

        options = flexmock(quiet=True)

        session = mock_session(
            target,
            source,
            task_success=False,
            task_result={'this': 'should not be in output'}
        )

        args = build_cli_args(target, source)

        rv = cli_containerbuild.handle_container_build(options, session, args)
        stdout_output, _ = capsys.readouterr()

        assert rv != 0
        assert stdout_output == ''
        assert not session.status['logged_in']

    @pytest.mark.parametrize('why', [
        '--nowait',
        'running in background'
    ])
    def test_no_wait(self, why, capsys):
        target = 'target'
        source = 'https://repo#revision'

        options = flexmock(quiet=True)

        session = mock_session(
            target,
            source,
            task_result={'this': 'should not be in output'},
            running_in_background=(why == 'running in background')
        )

        wait = False if why == '--nowait' else None
        args = build_cli_args(target, source, wait=wait)

        rv = cli_containerbuild.handle_container_build(options, session, args)
        stdout_output, _ = capsys.readouterr()

        assert rv is None
        assert stdout_output == ''
        assert session.status['logged_in']

    def test_background_priority(self):
        target = 'target'
        source = 'https://repo#revision'

        options = flexmock(quiet=True, weburl='x.org')

        session = mock_session(
            target,
            source,
            priority=5
        )

        args = build_cli_args(target, source, background=True)

        rv = cli_containerbuild.handle_container_build(options, session, args)

        assert rv == 0
        assert not session.status['logged_in']