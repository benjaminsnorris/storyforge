"""Dashboard timeline scatter: which scenes it plots, and how (evals F-059).

The scatter dropped every scene on day 0 or before the story (Carol's
Stave II memories, Gatsby's Louisville) and drew frame and vision scenes
on the line through the story's present."""

import json
import os
import re
import shutil
import subprocess

import pytest


def _dashboard(plugin_dir):
    with open(os.path.join(plugin_dir, 'templates', 'dashboard.html')) as f:
        return f.read()


def _timeline_points(plugin_dir, scenes):
    match = re.search(r'function timelinePoints\(scenes\) \{.*?\n\}', _dashboard(plugin_dir), re.S)
    assert match
    script = match.group(0) + f'\nconsole.log(JSON.stringify(timelinePoints({json.dumps(scenes)})));'
    out = subprocess.run(['node', '-e', script], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


@pytest.mark.skipif(shutil.which('node') is None, reason='node not installed')
def test_days_before_the_story_and_day_zero_are_plotted(plugin_dir):
    scenes = [{'id': 'night', 'timeline_day': '1'},
              {'id': 'boyhood', 'timeline_day': '-18250'},
              {'id': 'eve', 'timeline_day': '0'},
              {'id': 'undated', 'timeline_day': ''},
              {'id': 'bad', 'timeline_day': 'soon'}]
    points = _timeline_points(plugin_dir, scenes)
    assert [(p['id'], p['day'], p['index']) for p in points] == [
        ('night', 1, 0), ('boyhood', -18250, 1), ('eve', 0, 2)]


@pytest.mark.skipif(shutil.which('node') is None, reason='node not installed')
def test_frame_and_vision_are_off_the_present(plugin_dir):
    scenes = [{'id': 'frame', 'timeline_day': '400', 'time_mode': 'frame'},
              {'id': 'night', 'timeline_day': '1', 'time_mode': ''},
              {'id': 'week', 'timeline_day': '2', 'time_mode': 'summary'},
              {'id': 'grave', 'timeline_day': '370', 'time_mode': 'vision'}]
    points = _timeline_points(plugin_dir, scenes)
    assert [(p['id'], p['mode'], p['offPresent']) for p in points] == [
        ('frame', 'frame', True), ('night', 'scene', False),
        ('week', 'summary', False), ('grave', 'vision', True)]


def test_the_scatter_uses_the_helper_and_links_only_the_present(plugin_dir):
    html = _dashboard(plugin_dir)
    scatter = html[html.index('(function renderTimelineScatter()'):]
    scatter = scatter[:scatter.index('\n})();')]
    assert 'timelinePoints(sortedScenes)' in scatter
    assert 'day <= 0' not in scatter
    assert 'd > 0' not in scatter
    assert 'offPresent' in scatter
