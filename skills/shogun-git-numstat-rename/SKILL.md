---
name: shogun-git-numstat-rename
description: |
  git diff --numstat の改名（rename）略記（'dir/{old, new}/file' や 'old, new' の矢印区切り表記）を
  正しく新旧パスへ分解し、パスごとの追加/削除行数を正確に返す。--name-status と numstat の
  出力をパス文字列でそのまま突き合わせると、略記のせいで改名ファイルの行数が0扱いになり、
  区分・持ち場・パッケージ単位の行数集計が過小評価される落とし穴を防ぐ。
  「numstatの行数が合わない」「改名を含むPRの行数集計」「パスごとの追加削除行数」
  「rename detection」「diff --numstat 改名」で起動。
  Do NOT use for: ファイル数だけの集計（--name-status のみで足りる、行数は不要な場合）、
  改行を含む/引用符付きパスの特殊なエンコーディング解析が主目的の場合（本スキルは -z を
  使うため core-quotepath 起因のエスケープ問題自体は発生しないが、それ以上の深追いはしない）。
allowed-tools: Bash, Read
---

# shogun-git-numstat-rename — numstat の改名略記を正しく読む

## Overview

`git diff --numstat` は改名を検出すると（`-M` 指定時、既定でも類似度次第で自動検出されることがある）、
パス列を **略記** で返す:

```
8	5	espnet2/gan_tts/{vits => hifigan}/hifigan.py     ← 新旧で共通の親ディレクトリがある場合
17	13	espnet2/{asr/transducer => asr_transducer}/joint_network.py
```

一方 `git diff --name-status` は常に**完全な新パス**（略記なし）を返す:

```
R098	espnet2/gan_tts/vits/hifigan.py	espnet2/gan_tts/hifigan/hifigan.py
```

`numstat`の出力を「パス文字列」としてそのまま辞書のキーにし、`name-status`側の新パスで
引こうとすると、略記と完全パスの文字列が一致せず**引けない**。多くの簡易ツールは
「引けなければ0扱い」で握りつぶすため、**改名ファイルの行数が黙って0として集計される**。
ファイル数（`n_files`、`--name-status`だけで数える指標）は無事だが、**行数を伴う指標
（changed_lines、パッケージ/持ち場ごとの行数シェアなど）だけが過小評価**される、という
気づきにくい壊れ方をする。

north_star: **改名を含むPRの行数集計は、`--numstat -z` と `--name-status -z` を両方読み、
新パスで突き合わせる。略記文字列のパースで済まそうとしない。**

## When to Use

- 「PRごとの変更行数」「パッケージ/ディレクトリ単位の追加削除行数」を git から機械集計する時
- 対象PRに改名（ファイル移動・ディレクトリ再編）が含まれる可能性がある時
  （長期間・大規模なリファクタPRほど起きやすい）
- 既存の集計値が `git diff --stat` の合計と食い違う時（本スキルの落とし穴が疑われる）

Do NOT use for: ファイル数だけで足りる集計（`--name-status`のみで十分）。

## 読み取り専用の原則

`git diff --numstat -z` と `git diff --name-status -z` の読み取りのみ。対象リポジトリへの
書き込み・fetch・checkout は一切行わない。任意の git リポジトリで動作する（リポジトリパス・
比較対象commitは全て引数で渡し、特定プロジェクトの値をスクリプトへ埋め込まない）。

## 使い方

```bash
python3 skills/shogun-git-numstat-rename/scripts/numstat_paths.py \
  --repo <repo-path> --base <rev> --head <rev> [--paths <pathspec> ...] [--csv <out.csv>]
```

出力（1ファイル1行）: `status` `similarity`（rename/copyの類似度%）`old_path`（改名/コピー時のみ）
`new_path` `added` `deleted` `total` `binary`（真偽）。標準エラーに `n_files` と
`total_changed_lines` の合計も出す。

### `--paths` で対象を絞る（集計範囲を限定したい時に必須）

`--paths` は `git diff -- <pathspec> ...` のパススペックをそのまま渡す引数で、**空白区切りで複数指定できる**。
リポジトリ全体ではなく特定のディレクトリ配下だけを集計したい場合（例: パッケージ/持ち場単位の行数を
数えたい時）は必ず指定する。省略するとリポジトリ全体が対象になる。

```bash
# espnet2/ と espnet3/ 配下だけに絞って集計（change_stats系ツールでの典型的な使い方）
python3 skills/shogun-git-numstat-rename/scripts/numstat_paths.py \
  --repo /path/to/espnet --base <base-rev> --head <head-rev> --paths espnet2 espnet3

# 単一ディレクトリのみ
python3 skills/shogun-git-numstat-rename/scripts/numstat_paths.py \
  --repo /path/to/repo --base <base-rev> --head <head-rev> --paths src/mymodule
```

## なぜ `-z` で直るのか

`-z` を付けると、git は略記を**一切行わない**。改名/コピー行は「1レコード目に追加/削除行数と
空のパス欄、2レコード目に旧パス、3レコード目に新パス」という**3つの別々のNUL区切りフィールド**
になる（通常行は「追加数\t削除数\tパス」の1フィールド）。これは `--numstat -z` と
`--name-status -z` の両方で共通の構造であり、パスが省略・結合されることがないため、
新パスの完全一致で突き合わせても取りこぼしが起きない。

実際の生バイト列（`od -c`で確認、ESPnet #3449の例）:
```
8\t5\t\0 espnet2/gan_tts/vits/hifigan.py \0 espnet2/gan_tts/hifigan/hifigan.py \0
└──┬──┘   └──────────┬──────────┘         └───────────┬───────────┘
 3フィールド目が空       旧パス（次のNULまで）              新パス（次のNULまで）
```
（`name-status -z`も同型: `R098\0旧パス\0新パス\0`）

## `-z` を使わない場合の落とし穴（表で整理）

| ケース | `-M`（改名検出）あり | `-M` なし |
|---|---|---|
| 改名、新旧で共通の親ディレクトリあり | numstatは`dir/{old => new}/file`と略記。name-statusの完全パスと不一致で行数消失 | 改名として検出されず、削除＋追加の2行に分かれる（行数自体は保持されるが「同一ファイル」という情報が失われ、`old_path`が空になる） |
| 改名、共通の親ディレクトリなし | numstatは`old/path.py => new/path.py`（波括弧なし、`=>`のみ）と略記。同様に不一致 | 同上 |
| コピー（`-C`指定時） | `R`と同様に`C###`略記。同じ落とし穴 | コピー検出なし、新規追加として扱われる |
| バイナリファイル | numstatは`-\t-\tpath`（`-`は「行数不明」の意味であり0ではない）。`-`をそのまま`int()`すると例外、`0`として扱うと『バイナリだが変更なし』と『行数不明』を区別できなくなる | 同上（バイナリ判定自体は変わらない） |
| パスに空白・タブ・改行を含む | `-z`無しではgitがパスをC言語スタイルでクォート・エスケープする場合があり（`core.quotePath`設定次第）、タブ区切りパースが崩れうる | `-z`はNUL区切りのため、パス内の空白・タブ・改行はエスケープなしでそのまま安全に扱える（NULはパスに出現し得ない） |

本スキルの`scripts/numstat_paths.py`は常に`-z`を使うため、上表の右列の問題も左列の問題も
発生しない。`--no-rename-detection`オプションで`-M`を外すこともできるが、その場合は
改名が削除＋追加の2行に分かれる（`old_path`は常に空になる）ことを理解した上で使うこと。

## 検証（このスキル作成時に実施した再現テスト）

ESPnet リポジトリ（`R=/Users/somekimasao/Documents/espnet`）で、`queue/reports/espnet_task_change_stats/parts/stats_espnet2.csv`
のbase/head値を使い、修正前後で行数が変わる実例を2件再現（軍師の確認値と完全一致）:

1. **PR #3449 GAN-TTS**（base=`02a2b3126d6d` head=`3356f3cb02e0`）: 素朴な文字列突き合わせだと3件の改名
   （`hifigan.py`, `residual_block.py`, `wavenet.py`、いずれも`espnet2/gan_tts/vits/`→別ディレクトリ）の行数が
   消失し合計1869行になるところ、本スキルの`-z`読みでは**1978行**（軍師の確認値と一致、欠落分109行を回復）。
2. **PR #4479 ASR-Transducer**（base=`277ec3c33d2c` head=`c83abd7fb38c`）: 2件の改名のうち`joint_network.py`の
   行数(+17-13=30行)が消失し合計5512行になるところ、本スキルでは**5542行**（軍師の確認値と一致）。

このリポジトリ（multi-agent-shogun）自身でも1回動作確認済み: commit `41de9fc`（`skills/agent-status/SKILL.md`
→`skills/shogun-agent-status/SKILL.md`への改名を含む）で`n_files=2, total_changed_lines=6`
（`.gitignore`の+2-2と、改名ファイルの+1-1の合計）を得て、`git show --stat 41de9fc`
（"2 files changed, 3 insertions(+), 3 deletions(-)"）と一致することを確認済み。

## 品質ルール

- 改名を検出したい場合は必ず`-M`（既定でオン、`--no-rename-detection`で明示的に外せる）を使う。
- 行数を伴う集計では必ず`-z`版を使う。`-z`なしの`--numstat`をパスの文字列一致でパースするコードは
  改名を含むPRで静かに行数を落とす（本スキルの発見の核心）。
- バイナリファイル（`added`/`deleted`が空）は行数集計から除外する（0ではなく「不明」として扱う）。
- 対象リポジトリ・比較対象commitは常に引数で渡す。特定プロジェクト固有の値をスクリプトへ
  埋め込まない（読み取り専用・任意リポジトリ対応）。

## File Structure

```
skills/shogun-git-numstat-rename/
├── SKILL.md                  # 本ファイル
└── scripts/
    └── numstat_paths.py       # 汎用の道具（--repo/--base/--head必須引数、プロジェクト固有値なし）
```
