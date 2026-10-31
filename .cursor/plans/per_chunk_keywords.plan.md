---
name: per-chunk keywords
overview: "Before SAM runs a chunk, ask which keywords to search. SAM only runs those, review only shows those, and f only publishes those. a <word> adds a keyword. Headers say keyword N of M and chunk N of M."
todos:
  - id: picker
    content: "Steps 1-5: the picker in src/sam3_local/review_session.py"
    status: pending
  - id: labels
    content: "Step 6: header text in review_session.py"
    status: pending
  - id: review-all
    content: "Step 7: turn the picker on for --manifest and fix the chunk counter in scripts/review_all.py"
    status: pending
isProject: false
---

# Per-chunk keywords

All edits are in `C:\Users\Douglas\sam3local`, in two files: `src/sam3_local/review_session.py` and `scripts/review_all.py`. Find each place by the quoted text, not by line number. Copy the code as written.

## What the user sees

The first time a chunk is opened (by review or `--generate-only`):

```
Which keywords should SAM search on chunk_00_00?
  1. sphinx
  2. obelisk
  3. pillar
  4. ruins
  5. block
  6. boulder
  7. ribcage
Numbers like 3,5,6   [enter] all   a <word> add one:
```

- `4,5,6`: SAM searches ruins, block and boulder only. The pick is saved in the chunk's `review.json` as `picked_keywords`, so it is not asked again.
- enter: all of them.
- `a tomb`: adds tomb to this chunk and to the list every later chunk is offered, then shows the list again.
- In review, `k` shows the picker again.

Keywords left out are not searched, not shown, and not published by `f`. Results already cached for them stay on disk.

Review header:

```
NOW REVIEWING:  RUINS   (keyword 1 of 3, tiled)
Chunk:     chunk_00_00    Approved here: 0/3
Keywords:  [RUINS]  block  boulder
```

## Step 1. `review_session.py`: import and constructor

1. Directly above `from sam3_local.export import build_polygons_document, render_overlay_preview`, add:

   ```python
   from sam3_local.config_loader import normalize_prompts
   ```

2. In `ReviewSession.__init__`, directly below the parameter `locate_confidence: float = 0.15,`, add:

   ```python
           pick_keywords: bool = False,
   ```

3. At the end of `__init__`, directly below `self.locate_confidence = float(locate_confidence)`, add:

   ```python
           self.pick_keywords = pick_keywords
           # Keywords added with `a <word>` on earlier chunks.
           self.added_path = self.cache_root / "added_keywords.json"
           if pick_keywords:
               for word in load_json(self.added_path, {"keywords": []})["keywords"]:
                   if all(prompt["class"].lower() != word.lower() for prompt in self.prompts):
                       self.prompts.append(normalize_prompts([word])[0])
   ```

## Step 2. Three new methods

Add these directly below the method `_slots`:

```python
    def _picked(self, state: dict[str, Any], slot: dict[str, Any]) -> bool:
        """False for a keyword left out of this chunk's pick. No pick yet means every keyword."""
        picked = state.get("picked_keywords")
        return picked is None or str(slot["class"]).lower() in picked

    def _add_keyword(
        self, word: str, state: dict[str, Any], image_path: Path, image: Image.Image
    ) -> None:
        """Add a keyword to this chunk and to the list every later chunk is offered."""
        if any(str(slot["class"]).lower() == word.lower() for slot in state["slots"]):
            self.output(f"{word} is already on the list.")
            return
        self.prompts.append(normalize_prompts([word])[0])
        saved = load_json(self.added_path, {"keywords": []})
        saved["keywords"].append(word)
        atomic_write_json(self.added_path, saved)
        fresh = create_review_state(
            chunk_id=state["chunk_id"],
            image_path=image_path,
            image_size=image.size,
            prompts=self.prompts,
            config=self.config,
        )
        state["slots"].append(fresh["slots"][-1])

    def _pick_keywords(
        self,
        state: dict[str, Any],
        image_path: Path,
        image: Image.Image,
        ask_again: bool = False,
    ) -> None:
        """Ask which keywords SAM searches on this chunk. Asked once per chunk; [k] asks again."""
        if not self.pick_keywords:
            return
        if "picked_keywords" in state and not ask_again:
            return
        while True:
            self.output("")
            self.output(f"Which keywords should SAM search on {state['chunk_id']}?")
            for number, slot in enumerate(state["slots"], start=1):
                self.output(f"  {number}. {slot['class']}")
            answer = self.input("Numbers like 3,5,6   [enter] all   a <word> add one: ")
            parts = answer.replace(",", " ").split()
            if parts and parts[0].lower() == "a":
                if len(parts) == 2:
                    self._add_keyword(parts[1], state, image_path, image)
                else:
                    self.output("Usage: a <word>")
                continue
            count = len(state["slots"])
            if not parts:
                numbers = list(range(1, count + 1))
                break
            if all(part.isdigit() and 1 <= int(part) <= count for part in parts):
                numbers = [int(part) for part in parts]
                break
            self.output(f"Type numbers from 1 to {count}, press enter, or a <word>.")
        state["picked_keywords"] = [str(state["slots"][n - 1]["class"]).lower() for n in numbers]
        atomic_write_json(review_path(self.cache_root, state["chunk_id"]), state)
```

## Step 3. Leave unpicked keywords out

1. In `_slots`, replace its **first** line, `slots = list(state["slots"])`, with:

   ```python
           slots = [slot for slot in state["slots"] if self._picked(state, slot)]
   ```

   Leave the last line of `_slots` (`return slots or list(state["slots"])`) as it is.

2. In `_candidate`, replace:

   ```python
               if not slot["enabled"] or not slot["generation"]:
   ```

   with:

   ```python
               if not slot["enabled"] or not slot["generation"] or not self._picked(state, slot):
   ```

   This is what stops `f` publishing the keywords left out. Without it, chunk_00_00 and chunk_01_00 would publish all 7 cached keywords.

## Step 4. Ask before SAM runs

In **both** `generate` and `review`, directly below the line

```python
        state = self._load_or_create_state(chunk_id, image_path, image)
```

add:

```python
        self._pick_keywords(state, image_path, image)
```

## Step 5. The `k` command

1. In `review`, directly above `if command == "s":`, add:

   ```python
               if command == "k" and self.pick_keywords:
                   self._pick_keywords(state, image_path, image, ask_again=True)
                   mark_candidate_changed(state)
                   continue
   ```

2. In `_print_state`, directly below `self.output("[s] show overlay [o] crop ID  [e] on/off   [f] finish this image")`, add:

   ```python
           if self.pick_keywords:
               self.output("[k] pick keywords for this chunk")
   ```

## Step 6. Header text

In `_print_state`, replace everything from `keyword_line = "  ".join(` down to and including `self.output(f"Keywords:  {keyword_line}")` with:

```python
        how = "find then crop" if slot.get("path") == "large" else ("whole image" if self.no_tile else "tiled")
        keyword_line = "  ".join(
            f"[{item['class'].upper()}]" if item["slot"] == slot["slot"] else item["class"]
            for item in visible
        )
        self.output("")
        self.output("=" * 72)
        self.output(
            f"NOW REVIEWING:  {slot['class'].upper()}   "
            f"(keyword {slot_number} of {len(visible)}, {how})"
        )
        self.output(f"Chunk:     {state['chunk_id']}    Approved here: {approved}/{len(visible)}")
        self.output(f"Keywords:  {keyword_line}")
```

Keep `NOW REVIEWING:  ` (two spaces) at the start of that line exactly. The existing tests look for it.

## Step 7. `scripts/review_all.py`

1. In `main` there are two `ReviewSession(` calls. Find the one with `prompts=load_prompts_config(args.prompts)["prompts"],` (the `--manifest` one). Directly below its `auto_open=not args.no_auto_open,` line, add:

   ```python
           pick_keywords=True,
   ```

   Do not add it to the other call. The `--config` keyword workflow does not get the picker.

2. In `_browse`, replace:

   ```python
           print(f"\n=== [{unit_index + 1}/{len(units)}] {chunk_id} ({scope}) ===")
   ```

   with:

   ```python
           print(f"\n=== Chunk {unit_index + 1} of {len(units)}: {chunk_id} ===")
   ```

   The old `[1/2]` was the chunk counter, not a keyword counter.

## Not in this plan

- `small` / `large` / `both` when adding a keyword. In the `--manifest` review every keyword is tiled (small), and a large one would never be shown.
- Deleting cached results for keywords left out.
