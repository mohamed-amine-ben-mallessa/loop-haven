# Filters

Every value below was read from Looperman's own advanced-search form
(`POST /ajax/ajax_adv_search_modal`), not guessed from URLs. `GET /api/filters`
returns the same vocabulary as JSON.

LoopHaven accepts a **label**, a **numeric id** or a **slug** wherever a filter
is expected, and echoes back what it resolved in `resolved`:

```json
"resolved": { "genre": { "id": 54, "label": "Trap" } }
```

Unknown values return `422` with suggestions instead of an empty page.

---

## Loop filters — `GET /api/search`

| Query param | Upstream param | Notes |
|---|---|---|
| `genre` | `gid` | 69 genres |
| `category` | `cid` | 40 categories |
| `key` | `mkey` | 24 keys, accidentals normalised |
| `bpm` | `ftempo` + `ttempo` | shortcut for an exact tempo |
| `ftempo`, `ttempo` | `ftempo`, `ttempo` | explicit range; `ftempo` alone fills `ttempo` |
| `tsig` | `tsig` | `4/4`, `2/4`, `3/4`, `6/8` |
| `when` | `when` | date window |
| `order`, `dir` | `order`, `dir` | sort field and direction |
| `ppage` | `ppage` | results per upstream page: 25, 50, 100 |
| `page` | page path | page number (1-based) |
| `limit` | — | results returned by LoopHaven (1–50, default 10) |
| `keyword` | `keys` | `+include -exclude` |
| `mid` | `mid` | only items from this user id |
| `who` | `who` | followed-only / remove-ignored (unverified) |
| `favs` | `favs` | your favourites only (needs login) |

---

## Genres (`gid`)

| Value | id | Value | id | Value | id |
|---|---|---|---|---|---|
| 8Bit Chiptune | `56` | Acid | `52` | Acoustic | `3` |
| Afrobeat | `67` | Ambient | `2` | Big Room | `66` |
| Blues | `33` | Boom Bap | `65` | Breakbeat | `37` |
| Chill Out | `21` | Cinematic | `36` | Classical | `13` |
| Comedy | `51` | Country | `44` | Crunk | `39` |
| Dance | `17` | Dancehall | `55` | Deep House | `30` |
| Dirty | `23` | Disco | `18` | Drum And Bass | `11` |
| Dub | `5` | Dubstep | `49` | EDM | `64` |
| Electro | `42` | Electronic | `16` | Ethnic | `15` |
| Folk | `25` | Funk | `19` | Fusion | `46` |
| Garage | `24` | Glitch | `31` | Grime | `43` |
| Grunge | `53` | Hardcore | `48` | Hardstyle | `61` |
| Heavy Metal | `27` | Hip Hop | `7` | House | `22` |
| Indie | `63` | Industrial | `38` | Jazz | `6` |
| Jungle | `10` | Latin | `69` | Lo-Fi | `62` |
| Math Rock | `72` | Moombahton | `57` | Orchestral | `34` |
| Phonk | `70` | Pop | `50` | Psychedelic | `60` |
| Punk | `14` | Rap | `8` | Reggae | `4` |
| Reggaeton | `32` | Religious | `45` | RnB | `12` |
| Rock | `1` | Samba | `29` | Ska | `41` |
| Soul | `59` | Spoken Word | `47` | Techno | `9` |
| Trance | `28` | Trap | `54` | Trip Hop | `58` |
| UK Drill | `68` | Vaporwave | `71` | Weird | `35` |

---

## Categories (`cid`)

| Value | id | Value | id | Value | id |
|---|---|---|---|---|---|
| Accordion | `40` | Arpeggio | `47` | Bagpipe | `35` |
| Banjo | `36` | Bass | `2` | Bass Guitar | `43` |
| Bass Synth | `44` | Bass Wobble | `39` | Beatbox | `31` |
| Bells | `42` | Brass | `23` | Choir | `34` |
| Clarinet | `37` | Didgeridoo | `28` | Drum | `1` |
| Flute | `7` | Fx | `5` | Groove | `24` |
| Guitar Acoustic | `33` | Guitar Electric | `3` | Harmonica | `25` |
| Harp | `41` | Harpsichord | `30` | Mandolin | `32` |
| Orchestral | `22` | Organ | `26` | Pad | `11` |
| Percussion | `20` | Piano | `21` | Rhodes Piano | `46` |
| Scratch | `12` | Sitar | `9` | Soundscapes | `45` |
| Strings | `10` | Synth | `4` | Tabla | `8` |
| Ukulele | `38` | Violin | `29` | Vocal | `6` |
| Woodwind | `27` |  |  |  |  |

---

## Keys (`mkey`)

| Value | id | Value | id | Value | id | Value | id |
|---|---|---|---|---|---|---|---|
| A | `a` | Am | `am` | A# | `as` | A#m | `asm` |
| B | `b` | Bm | `bm` | C | `c` | Cm | `cm` |
| C# | `cs` | C#m | `csm` | D | `d` | Dm | `dm` |
| D# | `ds` | D#m | `dsm` | E | `e` | Em | `em` |
| F | `f` | Fm | `fm` | F# | `fs` | F#m | `fsm` |
| G | `g` | Gm | `gm` | G# | `gs` | G#m | `gsm` |

Flats do not exist upstream: `Bb` is stored as `am`, `Eb` as `dsm`. Sharps are
written with an `s`: `F#` is `fs`, `F#m` is `fsm`. Send the human spelling —
`Bb`, `F#m`, `C#` — and LoopHaven translates it.

---

## Time signatures (`tsig`)

| Value | id | Value | id | Value | id | Value | id |
|---|---|---|---|---|---|---|---|
| 4/4 | `4x4` | 2/4 | `2x4` | 3/4 | `3x4` | 6/8 | `6x8` |

---

## Date window (`when`)

| Value | id | Value | id | Value | id | Value | id | Value | id |
|---|---|---|---|---|---|---|---|---|---|
| Last 24 Hours | `1` | Last 48 Hours | `5` | Last 7 Days | `2` | Last 30 Days | `3` | Last 60 Days | `4` |

---

## Sort (`order`) and direction (`dir`)

| Value | id | Value | id | Value | id | Value | id |
|---|---|---|---|---|---|---|---|
| Date | `date` | Title | `name` | Author | `author` | Genre | `genre` |
| Tempo | `tempo` | File Size | `fsize` | Duration | `duration` | Downloads | `downloads` |
| Favourites | `favs` | Comments | `comments` |  |  |  |  |

Direction is `d` (descending) or `a` (ascending). Results per page (`ppage`) is
one of 25, 50, 100.

---

## Acapella filters — `GET /api/acapellas/search`

These are extra filters that only exist for acapellas. Every one was verified
against the live site.

| Query param | Upstream param | Meaning |
|---|---|---|
| `rights` / `ur` | `ur` | usage rights — `rights` is the readable alias |
| `mf` | `mf` | vocal gender |
| `style` | `style` | rap / singing |
| `vocal_type` | `type` | hook, verse, full song |
| `autotune` | `autotune` | used or not |
| `adult` | `adult` | `y` keeps adult content, `n` removes it |
| `mydl` | `mydl` | acapellas you already downloaded (needs login) |

### Usage rights (`ur` / `rights`)

| Value | id | Value | id |
|---|---|---|---|
| Free Commercial & Non Commercial | `1` | Free Non Commercial Only / Commercial Licence Required | `2` |

### Vocal gender (`mf`)

| Value | id | Value | id | Value | id |
|---|---|---|---|---|---|
| Male Vocal Only | `1` | Female Vocal Only | `2` | Both Male & Female | `3` |

### Vocal style (`style`)

| Value | id | Value | id | Value | id |
|---|---|---|---|---|---|
| Rap Only | `1` | Singing Only | `2` | Rap & Singing | `3` |

### Vocal type (`type` / `vocal_type`)

| Value | id | Value | id | Value | id |
|---|---|---|---|---|---|
| Hook | `1` | Verse | `2` | Full Song | `3` |

### Autotune

| Value | id | Value | id |
|---|---|---|---|
| Didn't Use Autotune | `1` | Used Autotune | `2` |

### Adult content

| Value | id | Value | id |
|---|---|---|---|
| Has Adult Content | `y` | Remove Adult Content | `n` |

---

## Not a filter: `did` (DAW)

`did` appears in a card's metadata and in the advanced-search HTML, but the
search ignores it — filtering on it returns unrelated results. LoopHaven
therefore exposes `daw` as a **card field only**, and has no `daw` query
parameter on purpose.

## The 5,000 cap

Looperman stops counting at 5,000 and only prints a total on the first page.
LoopHaven reports `total_capped: true` when the cap is reached and `total: null`
past the first page, rather than presenting a fabricated number as fact.
