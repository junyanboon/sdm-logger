"""Run with: python3 -m unittest test_log_reading"""
import contextlib
import io
import os
import unittest
from unittest import mock

import log_reading


def device(room, connectivity="ONLINE", ambient=21.5, mode="COOL", setpoints=None):
    traits = {
        "sdm.devices.traits.Temperature": {"ambientTemperatureCelsius": ambient},
        "sdm.devices.traits.Humidity": {"ambientHumidityPercent": 40},
        "sdm.devices.traits.ThermostatMode": {"mode": mode},
        "sdm.devices.traits.ThermostatTemperatureSetpoint": (
            {"coolCelsius": 20.0} if setpoints is None else setpoints
        ),
        "sdm.devices.traits.ThermostatHvac": {"status": "OFF"},
    }
    if connectivity:
        traits["sdm.devices.traits.Connectivity"] = {"status": connectivity}
    return {"traits": traits, "parentRelations": [{"displayName": room}]}


class MainTest(unittest.TestCase):
    def run_main(self, devices):
        env = {name: "x" for name in log_reading.REQUIRED_ENV}
        env["FORCE"] = "1"
        out = io.StringIO()
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(log_reading, "refresh_access_token", return_value="t"), \
                mock.patch.object(log_reading, "read_devices", return_value=(devices, 0)), \
                mock.patch.object(log_reading, "write_notion_page", return_value=True) as write, \
                contextlib.redirect_stdout(out):
            code = log_reading.main()
        pages = [call.args[1] for call in write.call_args_list]
        return code, [p["properties"]["Studio"]["select"]["name"] for p in pages], out.getvalue()

    def test_offline_thermostat_writes_no_row(self):
        code, studios, out = self.run_main([device("509 Bloor"), device("901 Yonge", "OFFLINE")])
        self.assertEqual((code, studios), (0, ["509"]))
        self.assertIn("901", out)
        self.assertIn("OFFLINE", out)

    def test_offline_device_with_missing_traits_is_not_a_failure(self):
        broken = device("901 Yonge", "OFFLINE")
        del broken["traits"]["sdm.devices.traits.Temperature"]
        code, studios, _ = self.run_main([broken])
        self.assertEqual((code, studios), (0, []))

    def test_online_thermostats_are_logged_as_before(self):
        code, studios, _ = self.run_main([device("509 Bloor"), device("901 Yonge")])
        self.assertEqual((code, studios), (0, ["509", "901"]))

    def test_unknown_connectivity_is_never_treated_as_offline(self):
        code, studios, _ = self.run_main([device("901 Yonge", connectivity=None)])
        self.assertEqual((code, studios), (0, ["901"]))


class SetpointTextTest(unittest.TestCase):
    def text(self, **kwargs):
        page = log_reading.notion_page(
            log_reading.extract_reading(device("509 Bloor", **kwargs)), "2026-11-24T10:05:00-05:00"
        )
        rich = page["properties"]["Setpoint"]["rich_text"]
        return rich[0]["text"]["content"] if rich else ""

    def test_cool_only_keeps_the_old_text(self):
        self.assertEqual(self.text(), "COOL 20")

    def test_heat_mode_writes_the_heat_setpoint(self):
        self.assertEqual(self.text(mode="HEAT", setpoints={"heatCelsius": 21.0}), "HEAT 21")

    def test_heat_setpoint_is_rounded_like_the_cool_one(self):
        self.assertEqual(self.text(mode="HEAT", setpoints={"heatCelsius": 20.050049}), "HEAT 20.05")

    def test_heatcool_writes_both(self):
        text = self.text(mode="HEATCOOL", setpoints={"heatCelsius": 19.0, "coolCelsius": 24.5})
        self.assertEqual(text, "COOL 24.5 HEAT 19")

    def test_no_setpoint_is_blank(self):
        self.assertEqual(self.text(mode="OFF", setpoints={}), "")


if __name__ == "__main__":
    unittest.main()
