# Disc Library for Home Assistant

Works out **which film is in your disc player** and shows its title and artwork in Home Assistant.

Players such as the Oppo UDP-203/205 report a lot about what they're playing (disc type, the title's exact running time, chapter count) but not the film's name. Disc Library uses those as a fingerprint:

1. **Taking the fingerprint:** once a disc's main feature is playing (title 1 or later, at least 45 minutes, so menu loops and extras are ignored), it reads the format, the running time to the second and the chapter count.
2. **A disc you've named before** is recognised immediately.
3. **The catalogue:** otherwise the fingerprint is matched against an index of disc releases built from [TheDiscDB](https://github.com/TheDiscDb/data). One clear match is used automatically.
4. **Several close matches** (films can share a running time to the second) appear as candidates. You pick the right one once with `disc_library.identify`, and that disc is remembered from then on.

The result is a sensor, e.g. `sensor.cinema_oppo_disc`:

| | |
|---|---|
| **State** | The film's title, or `No disc`, `Disc` (main feature not started yet), `Choose` (several candidates) or `Unknown disc` |
| **Attributes** | `media_title`, `media_channel` (e.g. "2022 · 4K UHD"), `entity_picture` (TMDB backdrop), `poster`, `tmdb_id`, `fingerprint`, `found_by` (`matched` or `named`) and `candidates` (title, year, poster, tmdb_id) |

Images come from TMDB's public image server, so no API key is needed.

## Installation

1. Copy `custom_components/disc_library` into your Home Assistant `config/custom_components/` folder. (HACS: add this repository as a custom repository of type *Integration*.)
2. Add the player(s) to `configuration.yaml` (or a package):

   ```yaml
   disc_library:
     players:
       - media_player.cinema_oppo
   ```

3. Restart Home Assistant.

The index is downloaded from this repository about a minute after start-up and then once a day. It is kept in `config/disc_library/index.json`. Set `index_url: ""` to stop downloads and supply your own index.

## Naming a disc

```yaml
action: disc_library.identify
data:
  entity_id: sensor.cinema_oppo_disc
  tmdb_id: 361743   # from the sensor's candidates
```

`disc_library.forget` clears the name given to the disc now in the player.

## The index

`data/index.json` is rebuilt every week by a GitHub Action (`scripts/build_index.py`), from the main features recorded in TheDiscDB. It is committed only when something changed.

TheDiscDB is a community project. Coverage is best for US releases. To add your own discs, see [TheDiscDB's contribution guide](https://thediscdb.com/help/contributing). It needs a computer with a Blu-ray/UHD drive.

## Credits

- Disc data: [TheDiscDB](https://github.com/TheDiscDb/data) (MIT licence).
- Images and film details: [TMDB](https://www.themoviedb.org/). This product uses the TMDB API but is not endorsed or certified by TMDB.
