"""The speaker-label convention for a brief's scripted lines (#513), as the
prompts say it: one wording, so every prompt says the same thing and a
change is one edit.

The gate reads a label (`gate._label_speaker`, through `gate._brief_lines`)
so its speaker check (#511) can check a speech tag that splits the line;
`references/scene-column-guide.md` is the author's version. `LABEL_RULE` asks
for only the form the gate reads with the least doubt, `Name: "line"`, one
character per label, so a prompt never teaches a form it can't read.
"""

#: For a prompt that writes or rewrites a brief's scripted lines
#: (`key_dialogue`, and a quoted line in `key_actions` or `outcome`)
LABEL_RULE = ('Label every quoted line with its speaker as `Name: "line"`: the name exactly '
              'as in characters.csv (no title, no possessive), one character per label, '
              'repeated for each line, even when the same character speaks again. Leave the '
              "label off only when it isn't clear who speaks.")

#: For a prompt that reads a brief's scripted lines into prose
LABEL_READING = ('A line written `Name: "line"` is that character\'s to say; the label is '
                 'not part of the line, so never write it into the prose.')
