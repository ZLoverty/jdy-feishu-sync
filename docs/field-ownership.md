# Field ownership

All Feishu fields are protected by default. A field becomes managed only when its stable Feishu `field_id` and Jiandaoyun source `name` are explicitly listed in `config/field_mapping.yaml`.

The ownership policy rejects unknown fields, duplicate source or target mappings, reserved bookkeeping fields, and transforms other than the explicitly supported `text` transform. Missing source fields are omitted from a proposed payload; they are never converted into null writes. P1 only builds and displays proposed payloads and never sends them to Feishu.
