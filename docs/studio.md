# Minos Studio · quick guide

Minos Studio is the web rule editor. On an open installation (the default, for example with
`docker compose up`) you go straight in; if the API requires keys, the Studio asks for an API key
with scope `manage` or `admin`. The Studio speaks English and Italian: the menu at the top right
switches language (the choice is remembered in the browser; the first time it follows the
browser language). The typical path, without writing JSON:

1. **Entity and schema.** In the workspace, *New entity*, then paste one or more sample objects:
   the schema is inferred as you type (types, nested objects, lists, dates, required fields). With
   several samples, fields that do not appear everywhere become optional. *Save as new version*;
   alternatively *Edit JSON Schema* to fix it by hand.
2. **Rule set.** *New rule set*, choose the entity. The editor opens with *Start → End*.
3. **Nodes.** Drag nodes from the palette onto the canvas (or click to add them) and connect the
   outputs (`pass`, `fail`, `next`, the switch branches) to the inputs. An output has a single
   connection: dragging a new one replaces the previous one. Cycles are prevented.
4. **Configuration.** Select a node to configure it in the *Node* panel:
   - *Condition*: field, operator and value, with nested **AND/OR** groups and **NOT** on every
     part. The operators offered depend on the field type; dates use a calendar.
   - *Over a list*: sum, count, minimum, maximum, average, "all", "at least one" over the items of
     a list, with a filter on the items and a value computed from each.
   - *Group*: several rules with one message per rule; *All the rules* evaluates every one of them
     to collect every error.
   - *Decision table*: input columns (fields or expressions), output columns and rows filled in
     like a spreadsheet, with short cells: empty = any, `EMBA`, `A, B` (one of), `>= 60`,
     `30..59`, `2027-01-01..2027-12-31`, `!= X`, `$.vars.name`. You choose which row applies (the
     first, the only one, the highest priority, all). The result goes into `$.vars`.
   - *Sub rule set*: reuses an already published rule set (pinned version), on the input object
     or on each item of a list; its messages appear in the result.
   - *Compute*: variables reusable in the other nodes (`$.vars.name`).
   - *Messages*: code, severity, text in Italian and English with inserted values
     (`{{vars.totalCfu}}`), the field concerned and attached data.
5. **Settings.** Mode (*Stop at the first error* or *Collect all errors*), language, schema
   version and constants (thresholds, dates, price lists).
6. **Save and validate** (`Ctrl+S`). Validation happens on the server against the schema: problems
   appear at the bottom, a click takes you to the node, and nodes with problems have a dashed
   border.
7. **Simulate** the draft on an input: the path lights up on the canvas, every node shows its
   outcome and exit, and the panel lists messages and output. *Save this simulation as a test*
   turns it into a regression test.
8. **Publish** from the *Versions* tab: fix, compatible change or breaking change. Publication
   fails if the draft is invalid or a test does not pass. You can promote right away to `dev`,
   `test` or `prod`, and later move any environment to any version (backwards too, for an instant
   rollback).
9. **Schedule** with *Move to… → From a date*: for example next year's rules in `prod` from
   1 August, while the current ones stay in force until then. Every call uses the version that is
   valid on its reference date.
10. **Compare** a version with the draft to see what will change before publishing.
11. **Export / import**: *Export* (toolbar or version) downloads rule set, schema and tests as a
    JSON file; *Import* on the workspace page loads it as a draft, in another installation or in
    another workspace.

The right-hand panel (*Node*, *Simulation*, *Tests*, *Versions*, *Settings*) closes with the ✕ or
with the last toolbar button: an icon bar remains and the graph widens to take all the space.
Selecting a node, *Simulate* or *Publish* reopens it on the right tab.

In the editor, *Undo* / *Redo* (`Ctrl+Z`, `Ctrl+Shift+Z`) undo changes to the graph (inside a text
field `Ctrl+Z` remains the text undo) and *Tidy up* arranges the nodes left to right following the
connections.

If two people edit the same draft, the second save is rejected and the Studio offers to reload.
Leaving with unsaved changes asks for confirmation.

To start from something concrete open the **Esempi** workspace: with `docker compose up` (or after
`python -m minos.cli seed-examples`) it holds every example in the repository (study plan,
e-commerce order, loan) already published to `prod`, with their tests, free to edit. `/demo`
instead shows them read-only with their inputs and the simulator, even without a database.
