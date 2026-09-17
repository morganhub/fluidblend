# TODO — what remains to complete the specification

Reference: the "Blender Director" specification v1.0 (16 September 2026, kept outside this public
repository) and [docs/roadmap.md](docs/roadmap.md). Status on 17 September 2026: version 0.3.0 (P0, live, lot 3); lot 4 is planned for 0.4.0.
Implementation scope and proof: [docs/production-p1.md](docs/production-p1.md).

## Amorce de reprise technique — version 0.3.0 du 17 septembre 2026

Ce bloc est le point d'entrée de la prochaine session. Le travail décrit ci-dessous est présent
dans la **version 0.3.0** (lot 3). Le lot 4 (B02, B04, B07) est prévu pour la 0.4.0. Relire
`git status` et ce récapitulatif avant toute reprise. Les modifications concernent le moteur, le
runtime Blender, les contrats/schémas, les tests, la fixture binaire et la documentation.

### État mesuré

- Catalogue : **43 opérations**, dont **19 P0 disponibles**, **21 P1 disponibles** et **3 P1
  indisponibles**. Une opération indisponible échoue au précontrôle avec
  `UNSUPPORTED_CAPABILITY`, même si aucun handler hôte n'existe.
- Nouvelles opérations P1 qualifiées : `shot.build`, `character.inspect`, `rig.map`,
  `rig.validate`, `animation.create`, `animation.apply`, `animation.loop`, `animation.bake`,
  `audio.prepare`, `lipsync.analyze`.
- Qualifiées ensuite (même jour) : recettes `walk`, `take_prop`, `give_prop`, mesures communes,
  `interaction.plan/apply/validate` (B03), `adjustment.preview/apply/revert` + `contact_lock`
  (B05), `tool.inspect/test/register` (B08), live coopératif (L09), panneau Director (B06). Dernière régression complète : **146 tests réussis en
  621,85 s** (après B04), 28 scénarios passés (A01–A13, B01, B03, B04, B05, B06, B08, L01–L09), lint/format/schémas OK.
- Après la 0.3.0 (non publié, vers 0.4.0) : fixture faciale `vitruvian-face`, `lipsync.apply` et
  `expression.apply` (B04).
- Opérations encore indisponibles : `animation.retarget`, `game.import_test`, `game.smoke_test`.
- Régression combinée : **121 tests réussis en 324,35 s**, avec A01–A13, B01 et L01–L08 sur
  Blender 5.2.2 LTS. Contrôles ciblés suivants : **98 tests unitaires**, **3 tests audio réels**
  (mono, stéréo et dépendance absente) et B01 renforcé réussi. Ruff, formatage, schémas et
  validation du skill passent. Rapport :
  [docs/acceptance-reports/implementation.md](docs/acceptance-reports/implementation.md).
- Inspection visuelle : les cinq poses Vitruvian ont été regardées et leurs empreintes sont dans
  `docs/reviews/vitruvian/review.json`. Le squat vérifie la déformation ; ses pieds flottent et ne
  constituent pas une preuve de contact. La validation artistique humaine reste en attente.

### Récapitulatif technique de l'implémentation

1. **Consolidation du moteur**
   - Précontrôle des capacités corrigé ; seconde vérification idempotence/source/révision sous le
     verrou projet ; empreintes de toutes les entrées admises vérifiées avant publication.
   - `task.cancel` ne déclare plus une tâche live annulée sans acquittement. L'état reste `unknown`
     et impose `task reconcile`; aucun processus Blender utilisateur n'est tué.
   - `doctor --project` compare désormais les observations au verrou sans le réécrire.
     `--write-lock` reste explicite ; les exécutables utilisés sont comparés aux SHA verrouillés.
   - Les audits, aperçus et validations portent un `evidence.json` lié à la révision, au SHA de la
     scène, aux entrées et aux artefacts. `shot.validate` refuse les preuves absentes ou périmées.
   - Blender batch et ouverture live utilisent `use_scripts=False`/`--disable-autoexec`. Un helper
     ZIP borné refuse traversées, liens, fichiers spéciaux, doublons Windows, bombes de taille ou
     de ratio ; il n'est pas encore exposé comme opération publique d'import.
   - Chemins Windows durcis (ADS, chemins relatifs à un lecteur, noms réservés, reparse points).
     Git LFS est documenté et testé depuis un clone neuf avec la vraie fixture `.blend`.

2. **Personnage Rigify et assemblage de plan**
   - Fixture CC0 Vitruvian skinnée générée de façon reproductible avec Rigify 0.6.10 : 37 436
     sommets, 1 063 os, aucun sommet sans influence. Source, licence, versions et SHA sont consignés
     dans `fixtures/vitruvian/`, `licenses/vitruvian.md` et le script de génération.
   - `shot.build` admet des manifests stricts et leurs licences/SHA, append local uniquement,
     refuse les bibliothèques liées et références manquantes, conserve le contenu/caméra/timing
     d'un plan existant et refuse un `instance_id` déjà présent.
   - `character.inspect`, `rig.map` et `rig.validate` produisent un profil sémantique explicite et
     cinq poses mesurées/rendues. Un contrôle absent bloque les opérations dépendantes.
   - Un garde interdit les applications aveugles de transforms aux armatures, objets animés ou
     meshes skinnés. La migration versionnée de rest pose/échelle/hiérarchie reste à écrire.

3. **Bibliothèque d'animation**
   - Contrats stricts `clip`/`clip-index`, Actions à slots, manifests avec profil, timing, couche,
     canaux possédés, seed, limites, contacts et événements ; index publié avec SHA du `.blend` et
     du rapport.
   - Recettes disponibles : `idle_neutral`, `walk`, `turn`, `look_at`, `reach`, `take_prop`,
     `give_prop`, `react`. `take_prop`/`give_prop` amènent la paume (`DEF-hand.X@0.5`) sur la prise
     d'un prop statique ou sur un point monde ; portée refusée au-delà de 95 % du bras.
   - Mesures communes (`anim/measures.py`) : chaque chiffre porte espace, fenêtre d'appui, pas
     d'échantillonnage, point de contrôle (os de déformation), tolérance et `passed` (`null` si non
     contrôlé). `walk` = cycle root motion sur pieds IK, glissement contrôlé à la création puis
     remesuré par `animation.apply` sur chaque répétition, avec le déplacement racine.
   - `animation.apply` crée des pistes NLA `REPLACE` et refuse conservativement tout chevauchement
     de canaux. `animation.loop` vérifie la continuité de valeur aux extrémités (hors canaux de
     root motion, répétés avec offset) et la pose évaluée à la couture.
   - `animation.bake` produit une variante d'export, retire contraintes/drivers de cette variante
     seulement, conserve la source et contrôle l'écart géométrique sous 1 mm aux trois images
     échantillonnées. Cela ne prouve ni tous les frames, ni les contacts, ni la continuité de vitesse.

3b. **Props et passation d'objet (B03)**
   - Asset `kind: prop` (`root_object`, `grips` nommés en mètres locaux) ; `shot.build` place la
     racine d'instance (`location`, `rotation_z` en radians). Prop de test `baton` CC0 généré à la
     demande par `scripts/generate_prop_fixture.py`, aucun binaire versionné.
   - `interaction.plan` (hôte) produit un plan relisible lié à la révision par `evidence.json` ;
     `interaction.apply` refuse un plan périmé ou modifié (`SCENE_CONFLICT`), un prop ayant déjà une
     autorité, des canaux de main occupés, une cible hors de portée. Transfert par deux `CHILD_OF`
     à influences en clés constantes, inverse calculée pour conserver la transformée monde.
   - `interaction.validate` rejoue exactement le code de mesure d'`apply` (contacts dans l'espace du
     prop, saut de passation, autorité unique, absence de cycle) et sort 0 avec
     `technical_pass: false` en cas d'échec : lire la métrique, pas le code de sortie.
   - Limites : personnages immobiles, prop rigide à l'échelle 1, mains ouvertes, pas de propagation
     du retiming d'un participant.

3c. **Ajustements Preview/Apply/Revert (B05)**
   - Un seul outil : `contact_lock`. Couche NLA additive (une Action + une piste `ADD`) sur la
     location du contrôle IK ; aucune source modifiée ; `revert` retire exactement cette couche, ou
     répond `SCENE_CONFLICT` si elle a été modifiée à la main.
   - Refus : contact déjà dans la tolérance, membre en FK, dérive > `max_correction_m` (fenêtre
     contenant un pas = déplacement, pas glissement).
   - Outils custom déclaratifs (B08) : `tools/custom/<id>/tool.json` borne un outil intégré et
     porte ses tests ; `tool.inspect` répond `unsupported` avec la raison (outil de base absent,
     rig sans IK) ; `tool.test` rejoue les tests en mémoire ; `tool.register` exige rapport
     intègre + tous tests réussis ; `custom_tool_id` applique les bornes au précontrôle. Aucun
     code n'est chargé depuis `tools/custom/`.
   - Reste : sept autres outils d'ajustement.

4. **Audio et dialogue préparatoire**
   - `audio.prepare` conserve la source, mesure puis normalise avec FFmpeg `loudnorm` en deux
     passes, convertit d'abord la mesure en mono, rééchantillonne à 48 kHz PCM16 et vérifie la sonie
     finale. Durées secondes/images restent rationnelles.
   - `lipsync.analyze` exécute réellement Rhubarb 1.14 en mode phonétique et valide les cues A–H/X.
     Il ne crée aucune animation faciale et ne vaut pas approbation du texte ou de la voix.

5. **Fiabilité live**
   - Identité enrichie d'un identifiant de session et d'une génération monotone de modifications,
     avec handlers depsgraph/undo/redo/load hors données de scène.
   - Identité et génération revérifiées avant exécution, avant publication et atomiquement avant
     reload. Les scénarios L06–L08 prouvent qu'une édition humaine concurrente est conservée.
   - Les appels restent synchrones sur le thread principal : progression coopérative, acquittement
     d'annulation et panneau Director ne sont pas implémentés.

6. **Interfaces et documentation**
   - Le catalogue et les schémas exposent modes, dépendances requises/optionnelles, cibles,
     paramètres de chemins et règle de publication. `AssetManifest`, `RigProfile`, `ClipManifest`
     et `ClipIndex` ont des schémas dédiés.
   - Dix requêtes P1 prêtes à copier ont été ajoutées au skill. README, roadmap, compatibilité,
     sécurité, CLI, références du skill et changelog décrivent désormais le périmètre réel.
   - Le rapport détaillé et les limites se trouvent dans
     [docs/production-p1.md](docs/production-p1.md). P2 reste volontairement à la demande.

### Point de reprise recommandé

1. Commencer par `git status --short`, puis relire ce bloc et `docs/production-p1.md`. Ne pas
   supprimer les fichiers non suivis : ils font partie de l'implémentation en cours.
2. Rejouer les contrôles rapides avant toute nouvelle modification :
   `ruff check .`, `ruff format --check .`, `fluidblend schema check` et
   `pytest tests/unit -q` via `.venv/Scripts/`.
3. Créer un commit de jalon seulement après revue du diff et vérification que la fixture
   `fixtures/vitruvian/character.blend` est bien prise en charge par Git LFS.
4. Fait : mesures communes de contacts/boucles, recettes `walk`, `take_prop`, `give_prop`,
   `interaction.plan/apply/validate` et B03. Le travail est dans le worktree, non commité.
5. Fait aussi : cycle Preview/Apply/Revert avec `contact_lock` (B05), registre d'outils
   déclaratifs `tool.inspect/test/register` (B08), live coopératif avec annulation acquittée (L09)
   et panneau Director (B06). Le lot 3 est clos côté scénarios ; restent les points `[~]`/`[ ]`
   listés plus bas (autres outils, autres interactions, relecture humaine du panneau). Garder `available: false` jusqu'au test Blender réel et
   au scénario d'acceptation correspondant.
6. Pour la livraison film/jeu, poursuivre dans l'ordre : fixture faciale + `lipsync.apply`/B04,
   retarget borné/B02, puis template Godot et import/smoke tests/B07. Ne pas démarrer P2 sans demande.

Legend: `[x]` done and proven by tests · `[ ]` not started · `[~]` partial. Every item becomes
`available: true` in the catalogue only with real Blender tests and an acceptance scenario; until
then it answers `UNSUPPORTED_CAPABILITY`.

## Done

- [x] Lot 0 — diagnosis, sourced decisions (`docs/sources.md`), locked Blender 5.2.2 LTS.
- [x] Lot 1 — P0 foundation: project scaffold, contracts, journal/revisions/locks/checkpoints,
      batch runtime (`scene.build`, `scene.inspect`, `scene.audit`, `animation.retime`,
      `shot.preview`, `game.export`), `shot.validate`, `film.assemble`, `providers.check`,
      acceptance A01–A13 (`docs/acceptance-reports/latest-p0.md`).
- [x] Lot 2 — live mode: runtime as an approved Blender add-on, identity check, isolated writes,
      instance lock, lost-response reconciliation and concurrent-edit guards, acceptance L01–L08.
- [x] Delivery: English skill + docs, CI (unit tests on Windows), `scripts/demo.ps1`, external tools
      discovery (`%LOCALAPPDATA%\fluidblend\tools`), sanitized dependency lock.

## Lot 3 — characters, animation library, adjustments (P1)

Spec §9, §10, §11, §12, §16.1, §18 (lot 3); acceptance B01, B03, B05, B06, B08. Estimate: 6–9 days.

### Rigs and characters (§9)
- [x] `rig.map`: semantic rig profile (`root`, `pelvis`, `head`, `left_hand_ik`, `right_foot_ik`…)
      independent of bone names; declare absent controls and what their absence prevents.
      First profile: Rigify 0.6.10 (`torso`, `hand_ik.L`, `foot_ik.L`, switches on `*_parent.L`).
- [x] `rig.validate` / `character.inspect`: test poses (arms up, bent elbow, bent knee, squat,
      torso twist), uninfluenced vertices, missing bones, problematic scales, deformation views.
- [x] Skinned reference character fixture with a full rig profile and a recorded license
      (candidate: CharMorph "Vitruvian" CC0 + Rigify; never Mixamo) → `fixtures/`, `licenses/`.
- [ ] Rest-pose / rig-scale / hierarchy fixes treated as migrations with regression tests.
- [~] Never apply transforms blindly on skinned or animated characters (guard + test).

### Animation library and layers (§10)
- [~] Clip manifests (`animation/clips/<clip_id>/`: Action + slot, rig profile, timing, loop,
      root-motion convention, contacts, events, owned channels, measurements) and
      `animation/recipes/` (recipes are code, not yet declarative files).
- [x] Initial library on the Rigify profile: `idle_neutral`, `walk`, `turn`, `look_at`, `reach`,
      `take_prop`, `give_prop`, `react` — each with supported rigs and parameters. Bounded recipes:
      no arm swing, heel roll or finger pose; none is artistically approved.
- [x] `animation.create`, `animation.apply`, `animation.loop`, `animation.bake`.
- [~] Logical layers (global motion, locomotion, upper body, hands/contacts, gaze, face, lips,
      secondary) mapped to NLA tracks and channel partitions; documented priority resolution;
      double-transform detection.
- [~] Blocking → spline → polish workflow support; never convert dense mocap to constant
      interpolation by default.
- [~] Procedural motion (§10.5): recorded seeds, amplitude ranges, anatomical limits (camera
      paths, secondary oscillation, blinks, extras variation).

### Interactions (§11)
- [x] `interaction.plan` / `interaction.apply` / `interaction.validate`: choreography manifest
      (participants, prop instance, interval, anchors, contact windows, ownership order) — one
      bounded kind, `prop_handoff`; the plan is bound to its revision and refused once stale.
- [x] Prop hand-off: attach with known offset → synchronized reach → constraint transfer keeping
      the world transform → release; validations for position jump, hand distance, ownership → B03.
- [x] Single authority on a prop's transform; no constraint cycles between characters.
- [~] Timing change propagates to contacts, gaze, events and associated audio; report breaks.
      Breaks are reported by `interaction.validate`; nothing is propagated yet.
- [ ] Other interaction kinds (handshake, shared gaze, two-handed carry, hand-off while walking),
      finger poses, wrist orientation, body/prop intersection test.

### Adjustment tools (§12)
- [x] Tool contract (§12.2): id, version, purpose, supported rigs, bounded parameters with units,
      time scope, affected channels, preconditions, preview mode, effects on sources, revert,
      tests, known limits (`ADJUSTMENT_TOOLS`, completeness enforced by a unit test). Lifecycle
      spec → code → unit tests → Blender fixture → before/after preview → measurement →
      registered capability, followed for `contact_lock`.
- [x] `adjustment.preview` / `adjustment.apply` / `adjustment.revert` (additive, removable NLA layer).
- [~] Tools (§12.3): done — `contact_lock` (measured contact error in the right space) → B05;
      its support-space variant is implemented but not exercised by a scenario. Remaining —
      `retime_segment` (keys and events order preserved), `scale_gesture`
      (rig limits, contacts preserved), `look_at_target` (no flips, limits), `root_path_adjust` (no double
      application), `loop_cleanup` (pose and optional velocity continuity), `curve_cleanup`
      (max deviation under threshold, contacts untouched), `expression_strength`.
- [x] `tools/custom/<tool_id>/` registry with `tool.inspect` / `tool.test` / `tool.register`;
      a bounded tool with tests or a clear limitation, never a fake success → B08. Declarative
      only (no code loaded); with one built-in tool a custom tool is a stricter `contact_lock`.
- [~] Quality measures (§16.1): foot slide ≤ 0.02 m, hand/prop contact ≤ 0.02 m, loop error,
      with the measurement defined (space, support window, sampling, control points, tolerance).
      Done: shared `anim/measures.py`, foot slide (world), palm/grip contact in the prop's space,
      hand-off jump and loop pose gated, seam velocity reported ungated. Remaining: `animation.apply`
      re-measures only the applied clip's contacts, not those of clips already on the rig.

### Native Blender panel (§12.4)
- [x] "Director" panel — target, parameters, range, Preview / Apply / Revert, state, report path;
      same operations as the CLI; bounded, debounced sliders; Apply = explicit new revision → B06.
      It lives in the runtime add-on (`fluidblend_runtime/director.py`), not in a separate
      `blender_addon/`. The preview does not use a temporary state in the session at all: the engine
      previews the published version in a separate process, so the session stays clean.
- [x] Human review of the panel in the GUI (17 September 2026): five usability defects found and
      fixed (empty character field, truncated messages, no redraw after a timer, stale work version
      not reported, unsaved scene blocking Apply/Revert with misleading "save" advice). Strict rule
      kept on purpose: Apply and Revert need a clean scene; `Reload file` discards on confirmation.
- [ ] In-viewport preview of an adjustment (today: figures and before/after frames only), and a
      demo shot where the fix is visible to the eye (the B05 fixture drifts 10 cm sideways).

## Lot 4 — voice and game target (P1)

Spec §13, §14, §17 (B02, B04, B07), §18 (lot 4). Estimate: 4–6 days.

### Film, audio and rendering (§13)
- [~] Film → sequence → shot organisation; `shot.build` assembling a shot from versioned assets
      (linked or appended, overrides inspected rather than applied blindly).
- [~] Dialogue pipeline: approved text and voices, `audio.prepare` (FFmpeg `loudnorm` two-pass,
      always `aresample=48000`), exact audio/frame mapping, source track never overwritten.
- [x] B04 done after 0.3.0: `vitruvian-face` fixture (13 pinned CC0 morphs as shape keys), face
      profile `charmorph-l3/1`, `lipsync.apply` (fractional frames, held cues gated on real mesh
      motion, own NLA track) and `expression.apply`. Remaining: cues shorter than two transitions
      are passed through unchecked; no co-articulation, jaw bone or tongue; audio not placed in the
      sequencer; manual-correction workflow is only "a track above"; no human review of the acting.
- [~] `lipsync.analyze` (Rhubarb 1.14, `-f json -r phonetic`) and `lipsync.apply` (cues A–H + X
      mapped to the rig's real face controllers, rest mouth, transitions, manual correction),
      `expression.apply` → B04.
- [ ] Animatic; blocking key frames and full-sequence preview; dense samples around contacts
      and transitions; before/after for every important fix; `technical_pass` →
      `visual_review_pending` → `art_approved` workflow with human decisions recorded in `reviews/`.
- [ ] Final render: image sequences with fixed resolution, frame rate, colour management,
      exposure, seed and engine settings; test an excerpt before a long sequence; simulation
      caches versioned by input hashes.

### Retargeting (§10.4)
- [ ] `animation.retarget` (bounded): preserve the source, identify source/target profiles,
      normalize conventions, verified reference pose, produce a new Action, test a few poses and
      a short excerpt first; record contacts and constraints → B02.
- [ ] Optional adapters as external add-ons (Retarget/Expy-Kit presets, Rokoko) — never vendored.

### Game (§14)
- [ ] Export contract: deform-skeleton variant, baked clips, compatible textures/materials,
      documented events, collision and LOD per target; recorded axes, units, root name, in-place
      vs root motion, loops, exported bones, influence limits, texture sizes, geometry budget.
- [ ] `templates/game-godot/` (Godot 4.7.2): test scene, controllable character, movement, at
      least two animation states, simple collision, one prop interaction (GDScript).
- [ ] `game.import_test` (headless `--import`, `.import` files verified) and `game.smoke_test`
      (GUT, exit 0/1) → B07; performance measured on a declared machine; if the engine is
      missing the game stays `not_tested`.
- [ ] `templates/game-web/` (Three.js r186, `let` only, no jQuery) only if the target is a web game.

## Lot 5 — studio extensions (P2, only on real demand)

Spec §1 (P2), §7.3, §10.5, §11, §12.4, §13, §18 (lot 5).

- [ ] Multi-shot render queue (task graph with chunks, no-overwrite frames, per-shot preview job).
- [ ] Cached simulations invalidated by geometry/timing/physics changes.
- [ ] Extras / crowd: phase offsets, speeds, trajectories with budgets.
- [ ] Optional providers with full declaration (§3.2): FreeMoCap, MoMask/BVH, motion catalogues,
      voice generators — source, version, code and weight licenses, data rights, network, account,
      cost, VRAM, formats, import/export test.
- [ ] Business MCP facade `fluidblend` over stable operations (stdio, typed parameters, central
      permissions, journal; logs on stderr; no public listener) (§7.3).
- [ ] Optional HTML/JS panel (modern JavaScript, no framework imposed) (§12.4).
- [ ] OpenTimelineIO export of the film timeline.

## Cross-cutting gaps against the specification

- [~] Live mode covers four operations only; client-owned MCP writes are not supported: the AI
      client must call `fluidblend run --mode live`. Shared operation ids and lock policy between
      shell and MCP tools remain to be exposed (§7.2).
- [x] Live edit generation and undo/redo/load signals; checked before execution, publication and reload (§7.4).
- [x] Progress and cancellation of long live calls; `task.cancel` for live tasks (§7.5) — cooperative
      timer steps, `progress.json`, cancellation believed only on `cancel.ack.json` (L09). The four
      live operations are single-step, so a stop lands before or after them; a long live operation
      must be written as a generator to be interruptible inside.
- [ ] Permissions enforced outside the agent's reach when the client allows it (hooks or client
      permission settings); the JSON permissions file remains a weak boundary (§15.3).
- [~] Archive imports: size and expansion limits, external references of imported `.blend`
      files inspected before enabling scripts/drivers (§15.3) — bounded ZIP helper and local append checks implemented; public archive import remains.
- [~] Dependency migration policy: no component update mid-production without a migration branch
      and a regression run (§3.3); `dependencies.lock.json` compared against the runtime probe.
- [x] Git LFS strategy for project binaries documented and verified end to end (§4.2).
- [ ] "Agent using the skill" tests (§17): a fresh session with only the skill, a test project and
      a realistic request; check reference selection, scope, no re-initialization, correct stops.
- [ ] Codex end-to-end check of the grafted skill (`.agents/skills/`) — only Claude Code exercised.
- [~] Final delivery report distinguishing designed / implemented / automatically tested /
      visually inspected / user-validated (§19); record visual inspections and user decisions in
      `reviews/` (automated evidence and assistant visual inspection exist; human artistic approval
      remains pending).
- [ ] Compatibility matrix upkeep: any Blender version other than 5.2.x announced only after a
      dedicated test run (§19).

## Not planned (out of scope by design)

- Direct calls to model APIs inside the engine, paid services, cloud asset transfers (§1.2).
- Universal retargeting between arbitrary rigs, "video generation as animation" (§1.3).
- Linux/macOS support: the specification targets a native Windows 11 workstation.
