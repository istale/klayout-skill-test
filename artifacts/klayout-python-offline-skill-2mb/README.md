# klayout-python-offline-skill.tar.gz (2MB split parts)

This directory contains a 2MB-chunk split of `klayout-python-offline-skill.tar.gz`.

## Reassemble
From this directory:

```bash
cat klayout-python-offline-skill.tar.gz.part-* > klayout-python-offline-skill.tar.gz
sha256sum -c klayout-python-offline-skill.tar.gz.sha256
```

## Notes
- Parts are created with: `split -b 2m -d -a 3`.
- If you change any part, re-run checksum generation.
