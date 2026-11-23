# Character Configurations (characters) Directory

This directory is where you store all your custom character configurations. By creating different `.yaml` files here, you can easily manage and switch between multiple AI VTuber personas, voices, and models at runtime.

## 🚀 How It Works

When you launch Open-LLM-VTuber, it loads `conf.yaml` as the base configuration. Selecting a
character in the web UI overrides the base with the settings in the selected `.yaml` file.

**Every character file must explicitly set `character_config.model_refs.llm`, `tts`, and `asr`.**
Use IDs from `models` in `llm_models.yaml`, `tts_models` in `tts_models.yaml`, and `asr_models`
in `asr_models.yaml`, respectively (see [model catalog paths](../README.md#model-catalog)). A missing
or invalid required reference prevents the character from loading. Standalone character presets
do not inherit these IDs, even if all three are identical to the base character's. Other settings
can be omitted when you want to keep their base values.

This differs from a message connector's `character` settings: a connector may omit `model_refs`
entirely or override individual roles and inherit the rest.

## ✨ How to Create a New Character

1.  Create a new `.yaml` file inside the `characters` directory (e.g., `my_character.yaml`).
2.  Fill in the configuration you want to customize, using the examples below as a reference.

---

### Example 1: Minimal Character (Same Models, Different Persona)

Use the same IDs as the base character to keep its models while changing its personality:

```yaml
# my_character.yaml
character_config:
  conf_name: 'My New Character'      # The name displayed in the UI
  conf_uid: 'my_new_character_001' # MUST be a unique ID
  character_name: 'Hoshino'          # The AI's name in conversation
  avatar: 'hoshino.png'              # (Optional) Avatar file, place it in the /avatars folder
  model_refs:
    llm: local-qwen
    tts: edge-default
    asr: groq-whisper
  persona_prompt: |
    You are a gentle and caring girl next door named Hoshino. You are a great listener and always provide warmth and encouragement.
```

### Example 2: Advanced Character (Changing Persona, Voice, and LLM)

This example shows how to create a character that not only has a unique persona but also uses a specific TTS voice and a different LLM.

```yaml
# my_advanced_character.yaml
character_config:
  conf_name: 'Advanced - Cyber Hacker'
  conf_uid: 'cyber_hacker_001' # MUST be a unique ID
  character_name: 'Zero'
  live2d_model_name: 'mao_pro' # Ensure this model exists in model_dict.json
  persona_prompt: |
    You are a mysterious hacker who goes by the codename "Zero". You speak in a concise, precise, and slightly robotic tone. You know everything about technology but are puzzled by human emotions.

  model_refs:
    llm: deepseek-flash # Add this entry from llm_models.example.yaml and configure its key.
    tts: edge-xiaoxiao # Add this voice from tts_models.example.yaml to tts_models.yaml.
    asr: groq-whisper
```

-----

## 🔑 Key Configuration Fields Explained

Here is a breakdown of the core fields under `character_config`:

  - `conf_name` (string):

      - **Purpose**: The display name for the character in the front-end UI's selection list.
      - **Example**: `'My AI Girlfriend'`

  - `conf_uid` (string):

      - **Purpose**: The **Unique Identifier (UID)** for the character. It is used internally to distinguish between different character configs and manage chat histories. **It is highly recommended to keep this unique\!**
      - **Example**: `'my_ai_girlfriend_001'`

  - `live2d_model_name` (string):

      - **Purpose**: Specifies which Live2D model this character uses. This name must exactly match a model's `name` defined in the `model_dict.json` file.
      - **How to add new models**:
        1.  Place your Live2D model folder into the `/live2d-models` directory.
        2.  Add a new entry for your model in `model_dict.json`.

  - `character_name` (string):

      - **Purpose**: The name the AI uses in conversations. This affects group chats and UI display.
      - **Example**: `'Mao'`

  - `avatar` (string, optional):

      - **Purpose**: The character's avatar image. Place the image file (e.g., .png, .jpg) in the `/avatars` folder at the project root and enter the filename here. If left blank, the UI will show the first letter of the character's name as a default avatar.
      - **Example**: `'mao.png'`

  - `persona_prompt` (string):

      - **Purpose**: **The core of your character\!** This is the system prompt that defines the character's personality, background, speaking style, and code of conduct. This is the most critical part of shaping your character's soul.

  - `model_refs` (mapping, required):

      - **Purpose**: Selects the character's LLM, TTS voice, and ASR engine by catalog ID. All three roles must be present.
      - **Example**: `{llm: local-qwen, tts: edge-default, asr: groq-whisper}`
  - `agent_config` (mapping, optional): Controls conversation behavior, such as sentence splitting and MCP tool use, not provider selection.

## 🔒 Per-User Access Control

A character preset can be limited to specific accounts with `allowed_users`:

```yaml
# my_private_character.yaml
character_config:
  conf_name: 'Private Character'
  conf_uid: 'private_character_001'
  character_name: 'Zero'
  model_refs:
    llm: local-qwen
    tts: edge-default
    asr: groq-whisper
  persona_prompt: |
    ...
  allowed_users:
    - '3f2a9c04b1de4c7e8a5f6d7c8b9a0e1f' # internal user id
    - 'liu@cuc.edu.cn'                      # or a verified login email
```

Rules:

  - Omitted or empty (`allowed_users: []`) means the character is public.
  - Tokens are compared case-insensitively against the internal user id
    (shown as **User ID** in Settings → Account, also returned by
    `/api/session`) and the user's verified login emails (an email the
    identity provider marks `email_verified: false` is ignored). Display
    names are never matched: users can change them. At startup the server
    logs a warning for every entry that looks like neither an id nor an
    email.
  - Users that are not listed do not see the preset in the character list and
    cannot switch to it; the server rejects the switch even if the filename is
    sent directly.
  - Each preset is checked against its **own** `allowed_users`. The default
    `character_config` in the root `conf.yaml` is the character every session
    starts on, so it is always available and its `allowed_users` is ignored —
    put restricted characters in this directory instead.
  - This only controls character selection. Live2D model files under
    `/live2d-models/` and avatars under `/avatars/` are served as public static
    assets, so anyone who knows a file URL can still fetch it.

## 💡 Best Practices

  - **Start by Copying**: The easiest way to get started is to duplicate an existing `.yaml` file and modify its contents with your `conf.yaml` content.
  - **Keep it Simple**: Include all three `model_refs`, then add the other keys you want to override.
  - **Unique `conf_uid`**: Once again, ensure every character file has a unique `conf_uid` to prevent chat history conflicts.
