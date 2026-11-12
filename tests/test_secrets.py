import unittest

from mk96env_core.secrets import find_secrets

GITHUB_TOKEN = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"


def scan(text: str):
    return find_secrets("commands/example.md", {"": text.encode("utf-8")})


class FindSecretsTest(unittest.TestCase):
    def test_prose_about_secrets_is_not_a_secret(self):
        text = (
            "- **Never log secrets or personal data** (passwords, tokens, full card numbers).\n"
            "- Never write secrets (keys, tokens, passwords, connection strings) in code.\n"
            "Use `token: $GITHUB_TOKEN` or `password=<your password>` placeholders.\n"
            "Authorization: Bearer $API_TOKEN\n"
        )
        self.assertEqual(scan(text), [])

    def test_real_token_is_found_with_its_location_and_masked(self):
        findings = scan(f"line one\nexport GH={GITHUB_TOKEN}\n")
        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertEqual((finding.key, finding.line), ("commands/example.md", 2))
        self.assertNotIn(GITHUB_TOKEN, finding.masked)

    def test_private_key_block_is_found(self):
        self.assertEqual(len(scan("-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n")), 1)

    def test_hardcoded_password_assignment_is_found(self):
        self.assertEqual(len(scan('db_password = "s3cr3tPassw0rd!"\n')), 1)

    def test_quoted_json_keys_are_found(self):
        self.assertEqual(len(scan('{"apiKey": "abcd1234efgh5678"}\n')), 1)
        self.assertEqual(len(scan('"GITHUB_TOKEN": "abcdefgh12345678"\n')), 1)

    def test_bearer_tokens_and_credentials_in_urls_are_found(self):
        self.assertEqual(len(scan("Authorization: Bearer abcdef1234567890abcdef\n")), 1)
        self.assertEqual(len(scan("url: https://user:hunter22@git.example.com/repo.git\n")), 1)

    def test_binary_files_are_skipped(self):
        self.assertEqual(find_secrets("mods/x", {"icon.png": b"\xff\xd8\xff" + b"\x00" * 10}), [])


if __name__ == "__main__":
    unittest.main()
