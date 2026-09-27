---
name: shogun-git-first-integration-finder
description: |
  あるパス（ファイル・ディレクトリ）が任意の git リポジトリの本流ブランチ（例: upstream/master,
  origin/main）に最初に取り込まれた merge/squash/direct commit と、その PR 番号・日付を、
  読み取り専用の git 操作だけで特定する。改名・分割・削除→再追加・大型バージョン取り込み
  merge・「is-ancestor は真だがそのcommitのtreeにはファイルが無い」偽陽性（P8）といった
  落とし穴を踏まずに調べたい時に使う。「このタスク/機能はいつ本流に入った」「初回追加PRを探して」
  「git考古学」「first integration」「いつmasterに入った」で起動。
  Do NOT use for: 現在のブランチの単純な blame/history 参照（git log/blame で足りる場合）、
  リポジトリへの書き込みが必要な作業（本スキルは fetch/checkout/worktree/stash を一切行わない）。
allowed-tools: Bash, Read
---

# shogun-git-first-integration-finder — 初回統合コミット特定

## Overview

「このファイル（またはディレクトリ）は、いつ・どの PR で本流ブランチに最初に入ったか」を、
読み取り専用の git コマンドだけで特定する。ESPnet リポジトリのタスク年表調査（軍師 cmd_espnet_task_history_001）
で確立した手法を汎用化したもの。対象リポジトリ・本流ブランチ名は毎回引数で渡す（ESPnet 固有の値は
埋め込まない）。

north_star: **「候補は道具が出す。答えは人が git log -1 と merge-base --is-ancestor で確かめてから書く」**
道具の出力を検証なしに転記した行は不可（quality_rules 参照）。

## When to Use

- 「〇〇はいつ本流に入ったか」「初回追加 commit と PR 番号を調べて」と言われた時
- 複数の機能・タスク・モジュールについて、取り込み年表やマイグレーション履歴の表を作る時
- 改名・分割・統合の多い長期リポジトリで、単純な `git log --follow` や `git blame` では
  答えが信用できないと分かっている時（下記の落とし穴 P1〜P8 のいずれかに当てはまる場合）

Do NOT use for: 単に「このファイルの変更履歴を見せて」程度の用途（`git log -- <path>` で足りる）。
書き込み・fetch・checkout が必要な作業（本スキルは対象リポジトリを一切変更しない）。

## 読み取り専用の原則（絶対厳守）

対象リポジトリに対して実行してよいのは次のサブコマンドのみ:
`git log / show / ls-tree / rev-list / merge-base / cat-file / diff`（すべて読み取り）。

**禁止**: `git fetch` / `git checkout` / `git worktree` / `git stash` / `git reset` / `git pull`。
対象リポジトリのメイン作業ツリーは他の作業者・他エージェントが使用中であることが多い。
本流ブランチの ref（例 `upstream/master`）は呼び出し時点の値に固定し、途中で動いても再取得しない。

## Instructions

### Step 0: 対象と本流 ref を確認する

- リポジトリのパス（`--repo`）と、本流ブランチの ref 名（`--ref`。例: `upstream/master`, `origin/main`）
  をユーザーまたはタスクから確認する。これらは絶対にスクリプトへハードコードしない。
- 調べたいパス（ファイルまたはディレクトリ）を1つ以上リストアップする。

### Step 1: 候補を道具で出す

```bash
python3 skills/shogun-git-first-integration-finder/scripts/probe.py \
  --repo <repo-path> --ref <mainline-ref> <path> [<path> ...]
```

出力例:
```
espnet2/tasks/slu.py    M=f2f1b7c0527 2022-09-06 merge  PR=4569  O=fa1d97232f4 2022-08-11 name@add=espnet2/tasks/slu.py | Add new SLU task |
```

道具は次を自動で行う（詳細は `scripts/probe.py` の docstring）:
1. `--full-history --diff-filter=A` で最古の追加 commit 候補（O）を全て列挙（P3 対策）
2. 改名連鎖を辿る。ただし「新名が追跡中パスと一致」かつ「旧名がその commit で消滅済み」の
   R 行のみ真の改名として採用（P2 対策。単なる類似ファイルへの誤ジャンプを排除）
3. `git rev-list --first-parent <ref>` の鎖上で、O を祖先に持つ最古の commit M を
   `merge-base --is-ancestor` の二分探索で求める（P1 対策。ancestry-path は使わない）
4. **P8 検査**: M の tree に実際にそのパスがあるかを `cat-file -e` で確認。無ければ
   （枝内で追加→削除されていた場合）鎖を先に進めて最初に実在する commit を M に取り直す
5. PR 番号・日付（committer date 優先）・author≠committer の注記を付ける

### Step 2: 道具の候補を必ず手で確認する（省略不可）

道具の出力は候補に過ぎない。各行について以下を自分で実行し、結果を報告に残す:

```bash
R=<repo-path>

# (a) O が M の祖先であること（真）
git -C $R merge-base --is-ancestor <O> <M>; echo $?      # 0 でなければならない

# (b) O が M の第1親の祖先でないこと（偽）＝ M が「最も古い」統合commitであることの確認
git -C $R merge-base --is-ancestor <O> $(git -C $R rev-parse <M>^); echo $?   # 1 でなければならない

# (c) step3b / P8: M の tree に実際にパスがあること
git -C $R cat-file -e <M>:<path>; echo $?                 # 0 でなければならない（失敗ならM取り直し）

# (d) M の日付・題名・PR番号
git -C $R log -1 --format='%H%n%s%n%cd (author %ad)' --date=short <M>
```

(a)(b)(c) の3点セットが全て確認できて初めて、その行を「確定」として書いてよい。
(c) が失敗した場合は道具の M を鵜呑みにせず、`git log --first-parent --diff-filter=AD --name-status`
でそのパスの追加/削除イベントを first-parent 鎖上で洗い出し、実際に存在する最初の commit を
M に取り直すこと（下記 P8 の実例を参照）。

### Step 3: 削除→再追加・分割・統合を確認する

```bash
git -C $R log --first-parent --diff-filter=AD --name-status --format='%h %cd %s' --date=short <ref> -- <path>
```
A（追加）と D（削除）が交互に出れば、道具が拾った O が「後の再追加」である可能性がある。
最古の A を採用しつつ、削除→再追加の経緯を注記に書く（SpeechLM の実例を参照）。

### Step 4: レシピ/設定/ドキュメント側の先行を確認する（P7。該当する場合）

同種の設定・レシピ・ドキュメントディレクトリに対しても Step 1〜2 を実行し、
その M がコード本体の M より早ければ、「レシピ先行: `<path>` `<M hash>` `<日付>`
`<PR番号 or PR番号なし>`」と注記する（P7 参照）。

### Step 5: 表に書く

7列固定: `| 現在の名前 | 初回追加日 | PR / merge commit | 当時の名称 | 根拠URL | 初回追加 commit（作者側・日付） | 注記 |`
（用途に応じて列名は調整してよいが、「PR/commit」「当時の名称」「根拠URL」「注記」の4種の情報は必ず残す）

## Pitfalls（P1〜P8。実測で確認済み。全てこのスキルのコードとテストに反映済み）

| ID | 何が起きるか | なぜ | 対処 |
|----|--------------|------|------|
| P1 | `git log --ancestry-path --merges --first-parent <O>..<ref>` が常に空を返す | first-parent 走査は枝側の commit（O）に到達しないため ancestry-path が成立しない | first-parent 鎖上で「O を祖先に持つ最古の commit」を `merge-base --is-ancestor` の二分探索で求める（`probe.py` の `integrating()`） |
| P2 | `--follow` が改名でなく「類似ファイルからのコピー」に飛ぶ | 例: st.py/mt.py/slu.py が無関係な asr_transformer.py→asr.py の改名を「自分の旧名」として誤検出 | R行を採用するのは (a) 新名が追跡中パスと一致し、かつ (b) その commit で旧名が `cat-file -e` で消滅確認できる場合のみ |
| P3 | 既定の history simplification が、tip に存在しないパス（旧名）の追加 commit を落とす | git log の既定挙動 | 追加 commit の探索には必ず `--full-history` を付ける |
| P4 | ディレクトリに `--follow` は効かない | git の仕様 | ディレクトリ（レシピ種別等）は `--follow` を使わず、配下の任意ファイルの最古 A（`--full-history`）→ M。旧パスへの改名済みディレクトリは旧パスで引く |
| P5 | author date と committer date の食い違い | フィーチャーブランチでの開発期間とマージのタイムラグ | 日付は M の committer date を正とする。O の author date は別列に併記。M 自体で author≠committer なら注記 |
| P6 | 大型バージョン取り込み merge で多数の機能が同時に入る | メジャーリリースの一括統合 | 注記に「vX.Y.Z 取り込み merge、作者側 commit は YYYY-MM」と書く |
| P7 | コード本体より、同種の設定・レシピ・ドキュメント側の初出の方が早いことがある | 新機能はまず設定/レシピ/ドキュメントの雛形やIssue起票的なプレースホルダとして先に置かれ、実装コードは後から追いつくことがある | 同種のレシピ/設定ディレクトリ（例: コードが `espnet2/tasks/st.py` なら `egs2/*/st1` 相当）についても本手順を実行し、その M がコード本体の M より早ければ注記に「レシピ先行: `<path>` `<M hash>` `<日付>` `<PR番号 or PR番号なし>`（当時使われていた学習エントリ: `<path>`）」と明記する（Step 4 参照） |
| **P8** | `is-ancestor(O, M)` が真でも、**M の tree にそのパスが実在するとは限らない**（同じPRブランチ内で追加→削除、または改名） | O がフィーチャーブランチ上に存在した時点では祖先関係は成立するが、そのブランチが M にマージされる前に該当ファイルが再度削除・改名されていることがある | `cat-file -e <M>:<path>` で必ず確認（`scripts/probe.py` が自動実行）。無ければ first-parent 鎖を先に進め、最初に実在する commit を M に取り直す |

### P8 の実例（このスキルの起源）

ESPnet の `espnet3/systems/tts/system.py` は、素朴な `is-ancestor` 判定だけだと候補
`33078144e20`（PR#6338, 2026-06-11）が「最古の統合 commit」に見えるが、
`git cat-file -e 33078144e20:espnet3/systems/tts/system.py` は失敗する（ファイルがその
commit の tree に存在しない）。実際にこのパスが first-parent 鎖上で実体を持つのは
`b930ea2422d`（PR#6514, 2026-08-25）が最初であり、真の初回統合はこちら。
候補ブランチの O（`0eb62d66ced`, 2026-03-23）はマージ前に削除されていた偽陽性だった。

## 品質ルール（厳守）

- **推測禁止**: 全ての日付・PR番号は、道具が出した M の hash を `git log -1` で自分で表示して
  確かめた値だけを書く。道具の出力の丸写しは不可。
- 確認できない項目は「不明」とし、直下に理由（例: 旧名が特定できない、候補が本流の祖先に無い、
  候補数が多すぎて確定できない）を1行書く。空欄禁止。
- URL は PR があれば `pull/<N>`、無ければ `commit/<M の完全40桁hash>`（短縮hash不可）。
- 世代違い・統合/分割・改名（同種の別モジュールへの置き換え等）は注記に必ず書く。
- 読み取り専用。`fetch`/`checkout`/`worktree`/`stash` は絶対に使わない。本流 ref は調査開始時の
  値に固定し、途中で動いても再取得しない。
- GitHub API（`curl https://api.github.com/repos/<owner>/<repo>/pulls/<N>`）は PR題名確認の
  補助としてのみ使ってよい。git 履歴と食い違えば git を正とし、その旨を注記する。

## 検証（このスキル作成時に実施した再現テスト、ESPnet リポジトリで実施）

R=`/Users/somekimasao/Documents/espnet`, ref=`upstream/master`（固定コミット `5c51f9a0003`）で
以下3件を独立に再現し、既知の確定値と一致することを確認済み:

1. `espnet/bin/lm_train.py`（LM, ESPnet1）→ M=`fd0464a6140`, PR=52, 2018-01-02, O=`62710c1a18e` 2017-12-30
2. `espnet3/systems/tts/system.py`（ESPnet3 TTS, P8実例）→ M=`b930ea2422d`, PR=6514, 2026-08-25, O=`bbd3caf874` 2026-08-07
3. `egs2/TEMPLATE/enh_asr1`（レシピ種別, P8実例・ディレクトリ）→ M=`42eb3108ae3`, PR=4226, 2022-04-19

いずれも `scripts/probe.py` の出力を Step 2 の (a)(b)(c)(d) 手順で手動確認済み。

## File Structure

```
skills/shogun-git-first-integration-finder/
├── SKILL.md          # 本ファイル
└── scripts/
    └── probe.py       # 汎用化した道具（--repo / --ref 必須引数、ESPnet固有値なし）
```
