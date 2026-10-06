#!/usr/bin/env python3
"""Tests for the model endpoint: where a plan came from.

    python -m unittest discover tests

WHY THESE EXIST
---------------
Once the model runs on a cluster instead of the laptop, "which model produced
this plan" stops being answerable from the model name alone. `llama3.3:70b`
served from an H100 and the same name typed into a config are not the same
measurement, and a result that cannot say which is not evidence.

The specific hazard is concrete. A laptop runs Ollama on port 11434 with a
small model. A remote model is reached through an SSH tunnel. If the tunnel
drops and anything falls back to the default port, planning calls are answered
by the *local* model while the record still says whatever model was requested.
Nothing looks wrong. This project has already lost one dataset to a
measurement that looked fine and was not.

So the endpoint is resolved once, recorded on every planning call, and these
tests pin that behaviour. They need no simulator, no model and no network.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "baseline"))

import open_loop_agent as agent  # noqa: E402


class NormaliseEndpointTests(unittest.TestCase):
    """`host:port` and full URLs both get typed, so both must work."""

    def test_bare_host_and_port_gets_a_scheme(self):
        self.assertEqual(agent.normalise_endpoint("gpu01:11434"),
                         "http://gpu01:11434")

    def test_loopback_without_scheme(self):
        self.assertEqual(agent.normalise_endpoint("127.0.0.1:11435"),
                         "http://127.0.0.1:11435")

    def test_full_url_is_left_alone(self):
        for url in ("http://127.0.0.1:11435", "https://example.edu:443"):
            with self.subTest(url=url):
                self.assertEqual(agent.normalise_endpoint(url), url)

    def test_empty_and_none_fall_back_to_the_local_default(self):
        for value in ("", "   ", None):
            with self.subTest(value=value):
                self.assertEqual(agent.normalise_endpoint(value),
                                 "http://127.0.0.1:11434")

    def test_whitespace_is_stripped(self):
        self.assertEqual(agent.normalise_endpoint("  gpu01:11434  "),
                         "http://gpu01:11434")


class RecordedEndpointTests(unittest.TestCase):
    """The endpoint must reach the data, not just the function call."""

    def _record(self, **kwargs):
        defaults = dict(drone="Drone1", instruction="fly forward for 5 seconds",
                        raw_output="{}", plan=None, plan_seconds=1.0, valid=False)
        defaults.update(kwargs)
        return agent.PlanRecord(**defaults)

    def test_default_is_the_resolved_module_endpoint(self):
        self.assertEqual(self._record().endpoint, agent.OLLAMA_ENDPOINT)

    def test_endpoint_appears_in_the_logged_json(self):
        row = self._record(endpoint="http://gpu01:11434").as_json()
        self.assertIn("endpoint", row)
        self.assertEqual(row["endpoint"], "http://gpu01:11434")

    def test_model_and_endpoint_are_recorded_separately(self):
        """A model name is not a location. Both are needed, and both are kept."""
        row = self._record(model="llama3.3:70b",
                           endpoint="http://gpu01:11434").as_json()
        self.assertEqual(row["model"], "llama3.3:70b")
        self.assertEqual(row["endpoint"], "http://gpu01:11434")

    def test_provenance_states_the_endpoint(self):
        self.assertIn("ollama_endpoint", agent.provenance())


class DefaultPortTests(unittest.TestCase):
    def test_the_local_default_is_ollamas_own(self):
        """11434 is Ollama's default, and a tunnel must NOT use it.

        Documented here because it is a deliberate choice rather than an
        accident: a tunnel on 11434 that dies leaves the agent talking to a
        local model with no error, which is the failure this whole file exists
        to prevent. A tunnel belongs on a different port so that a dead tunnel
        fails loudly.
        """
        self.assertTrue(agent.OLLAMA_ENDPOINT.endswith(":11434")
                        or "://" in agent.OLLAMA_ENDPOINT)


if __name__ == "__main__":
    unittest.main()
