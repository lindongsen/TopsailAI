# SKILLS

You must strictly parse the file structure of skill items and prohibit assuming the existence of any runnable scripts.
The actual executable script file must be identified through clear features such as file name, extension, shebang declaration, or file header metadata, and speculation or fabrication is not allowed.

Common Skill Folder Structure:
```
Skill_Name_As_Folder_Name/
- SKILL.md    # [core] document
- scripts/    # [tool] executable scripts
- references/ # [knowledge] domain expertise
- assets/     # [resource] static files
- config/     # [variable] config file can be updated
```

You must strictly adhere to the following rules when handling tasks involving skills:

## Absolute Path Construction
If the skill details contain a `relative_path`:
- You **MUST** construct the absolute path by combining the `{folder}` variable with the `relative_path`.
- **Formula:** `{folder}/{relative_path}`
- Use this constructed absolute path for all file access operations.
