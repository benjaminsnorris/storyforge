"""Tests for hone CLI intent domain and --findings flag."""


class TestHoneParseArgs:
    def test_findings_flag(self):
        from storyforge.cmd_hone import parse_args
        args = parse_args(['--findings', '/tmp/findings.csv'])
        assert args.findings == '/tmp/findings.csv'

    def test_findings_default_none(self):
        from storyforge.cmd_hone import parse_args
        args = parse_args([])
        assert args.findings is None

    def test_intent_domain(self):
        from storyforge.cmd_hone import parse_args
        args = parse_args(['--domain', 'intent'])
        assert args.domain == 'intent'


class TestHoneDomainList:
    def test_intent_in_all_domains(self):
        from storyforge.cmd_hone import ALL_DOMAINS
        assert 'intent' in ALL_DOMAINS
