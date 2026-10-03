"""Tests for deploy configuration: systemd timer validity, Ansible syntax."""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


DEPLOY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy")


class TestSystemdTimer:
    """Verify systemd timer files are valid and match their descriptions."""

    def test_watchdog_timer_exists(self):
        assert os.path.exists(os.path.join(DEPLOY_DIR, "survey-bot-watchdog.timer.j2"))

    def test_watchdog_timer_every_5_minutes(self):
        with open(os.path.join(DEPLOY_DIR, "survey-bot-watchdog.timer.j2")) as f:
            content = f.read()

        # Find OnCalendar value
        match = re.search(r"OnCalendar\s*=\s*(.+)", content)
        assert match is not None, "OnCalendar not found in timer file"
        cal_value = match.group(1).strip()

        # Must be every 5 minutes
        valid_patterns = [
            r"^\*:0/5$",       # systemd syntax
            r"^\*:00/5$",
            r"^minutely$",      # NOT valid — this is every minute
            r"^hourly$",
        ]

        assert cal_value == "*:0/5", (
            f"Watchdog timer should run every 5 minutes, got '{cal_value}'.\n"
            f"Expected '*:0/5' (OnCalendar=*:0/5 means every 5 min)"
        )

    def test_watchdog_unit_refers_to_correct_service(self):
        with open(os.path.join(DEPLOY_DIR, "survey-bot-watchdog.timer.j2")) as f:
            content = f.read()

        match = re.search(r"Unit\s*=\s*(.+)", content)
        assert match is not None, "Unit= not found in timer"
        assert match.group(1).strip() == "survey-bot-watchdog.service"

    def test_service_file_exists(self):
        assert os.path.exists(os.path.join(DEPLOY_DIR, "survey-bot.service.j2"))

    def test_service_has_restart_always(self):
        with open(os.path.join(DEPLOY_DIR, "survey-bot.service.j2")) as f:
            content = f.read()
        assert "Restart=always" in content or "Restart=on-failure" in content

    def test_service_refers_to_correct_script(self):
        with open(os.path.join(DEPLOY_DIR, "survey-bot.service.j2")) as f:
            content = f.read()
        assert "bot.py" in content or "survey-bot" in content


class TestAnsiblePlaybook:
    """Verify Ansible playbook has correct structure."""

    def test_playbook_exists(self):
        assert os.path.exists(os.path.join(DEPLOY_DIR, "playbook.yml"))

    def test_playbook_basic_structure(self):
        import yaml
        with open(os.path.join(DEPLOY_DIR, "playbook.yml")) as f:
            data = yaml.safe_load(f)

        assert isinstance(data, list), "Playbook should be a list of plays"
        assert len(data) >= 1, "Playbook should have at least one play"

        play = data[0]
        assert "hosts" in play, "Play should have hosts"
        assert "tasks" in play, "Play should have tasks"
        assert len(play["tasks"]) > 0, "Play should have at least one task"

    def test_playbook_includes_bot_service(self):
        import yaml
        with open(os.path.join(DEPLOY_DIR, "playbook.yml")) as f:
            data = yaml.safe_load(f)

        tasks_text = str(data)
        assert "survey-bot" in tasks_text, "Playbook should reference survey-bot service"

    def test_playbook_includes_watchdog_service(self):
        import yaml
        with open(os.path.join(DEPLOY_DIR, "playbook.yml")) as f:
            data = yaml.safe_load(f)

        tasks_text = str(data)
        assert "survey-bot-watchdog" in tasks_text, (
            "Playbook should reference survey-bot-watchdog timer"
        )

    def test_playbook_includes_bot_timer(self):
        import yaml
        with open(os.path.join(DEPLOY_DIR, "playbook.yml")) as f:
            data = yaml.safe_load(f)

        tasks_text = str(data)
        assert "timer" in tasks_text.lower() or "systemd" in tasks_text.lower()

    def test_all_j2_files_use_template_vars_not_hardcoded_paths(self):
        """Every .j2 file in deploy/ must use {{ data_dir }}/{{ bot_dir }}/{{ bot_user }},
        not hardcoded paths like /opt/survey-bot or /var/lib/survey-bot."""
        hardcoded_patterns = ["/opt/survey-bot", "/var/lib/survey-bot"]
        j2_files = [f for f in os.listdir(DEPLOY_DIR) if f.endswith(".j2")]
        assert len(j2_files) > 0, "No .j2 files found in deploy/"
        for fname in j2_files:
            with open(os.path.join(DEPLOY_DIR, fname)) as f:
                content = f.read()
            for pattern in hardcoded_patterns:
                assert pattern not in content, (
                    f"{fname} contains hardcoded path '{pattern}'. "
                    f"Use {{ data_dir }} / {{ bot_dir }} template variable instead."
                )

    def test_playbook_templates_reference_j2_files(self):
        """Every template: src in playbook should point to a .j2 file."""
        import yaml
        with open(os.path.join(DEPLOY_DIR, "playbook.yml")) as f:
            data = yaml.safe_load(f)
        for play in data:
            for task in play.get("tasks", []):
                if task.get("template"):
                    src = task["template"]["src"]
                    assert src.endswith(".j2"), (
                        f"Template src '{src}' should end with .j2"
                    )


class TestSetupScript:
    """Verify setup.sh exists and references key components."""

    def test_setup_script_exists(self):
        assert os.path.exists(os.path.join(DEPLOY_DIR, "setup.sh"))

    def test_setup_references_playbook(self):
        with open(os.path.join(DEPLOY_DIR, "setup.sh")) as f:
            content = f.read()
        assert "playbook" in content.lower() or "ansible" in content.lower()
