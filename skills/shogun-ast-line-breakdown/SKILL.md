---
name: shogun-ast-line-breakdown
description: |
  Pythonファイルの各行を ast で「実コード / docstring / コメント / 空行」に、
  YAML・シェルファイルを「実設定 / コメント / 空行」に分けて数える。docstringは
  「行頭が引用符」という近似ではなく ast（モジュール/クラス/関数本体の先頭の文字列式）で判定し、
  コメントは tokenize で判定するため、文字列リテラルの中に偶然含まれる「#」を
  コメントと誤認しない。2つの実装（例: espnet2 と espnet3）の「行数の差」がdocstringの
  厚さやコメントの多さによるものか、実コードの差によるものかを切り分けたい時に使う。
  「行の内訳」「docstring行数」「実コード行数」「コメントと空行を除いた行数」
  「code vs comment vs docstring」「YAML項目数」で起動。
  Do NOT use for: 単純な `wc -l` で足りるファイル数・総行数だけの比較（内訳が不要な場合）、
  git diffの行数集計そのもの（改名を含む場合は shogun-git-numstat-rename を使う）。
allowed-tools: Bash, Read
---

# shogun-ast-line-breakdown — 行を「実コード/docstring/コメント/空行」に分ける

## Overview

2つの実装（世代・言語・スタイルの異なるコードベース）の「行数」を比べる時、素朴な
`wc -l` や「空行と#行を除いた行数」だけでは、**docstringの厚さの違い**が実コードの差に
見えてしまう。例えば espnet3 が espnet2 よりdocstringを厚く書く習慣なら、行数の差の一部は
「実装がより複雑だから」ではなく「コメント代わりの説明文が長いから」かもしれない。

north_star: **「実コード＋実設定」（docstring・コメント・空行を除いた行）を主指標にし、
両側を同じ規則で数えてから比べる。** 内訳（docstring行数・コメント行数）は副として残し、
「行数の差の何割がdocstringか」を示せるようにする。

## When to Use

- 2つの実装（別言語・別世代・別スタイル）の「行数の差」を比べる時、その差が
  docstring/コメントの書き方の違いによるものかを確かめたい時
- 「この実装は実質どれだけのコードか」を、コメント・空行に惑わされず知りたい時
- YAML設定ファイルの「項目数」（葉の数）を、コメント・空行を除いて数えたい時

Do NOT use for: git diffの行数集計そのもの（それは`shogun-git-numstat-rename`）、
ファイル数・総行数だけで足りる比較。

## 使い方

```bash
# gitリポジトリの特定commit時点のファイルを読む
python3 skills/shogun-ast-line-breakdown/scripts/line_breakdown.py \
  --repo <repo-path> --rev <commit-or-ref> --paths <path1> <path2> ... \
  [--exclude-regex <RE>] [--csv <out.csv>] [--label <L>]

# 作業ツリー上のファイルを直接読む（gitを介さない）
python3 skills/shogun-ast-line-breakdown/scripts/line_breakdown.py \
  --files <file1> <file2> ... [--exclude-regex <RE>] [--csv <out.csv>] [--label <L>]
```

`--paths`/`--files`はディレクトリでも個別ファイルでも良い。`--paths`はgit ls-treeで
再帰的にファイルへ展開し、`--files`は`os.walk`でディレクトリ配下を再帰的に辿ってファイルへ
展開する。展開の順序はディレクトリ名・ファイル名とも`sorted`で確定させており、同じ入力なら
常に同じ順でCSV/標準出力に現れる。渡した引数自体がシンボリックリンクの場合は辿らずそのまま
symlink行として記録するが、**ディレクトリを辿っている途中で見つけたシンボリックリンクの
サブディレクトリは黙って飛ばす**（`os.walk`の既定`followlinks=False`のまま。中まで辿る必要は
無いと判断した）。どちらのモードも
`--exclude-regex`は「渡した引数（ディレクトリ）」にではなく、**展開後の個々のファイルパス
それぞれ**に対して適用する（既定の除外は`README`/`RESULTS`/`.md`拡張子/`__pycache__`を含む
パス）。拡張子ごとの扱いは下記「YAML/シェルの内訳」・「Pythonのdocstring判定」の節を参照
（`.py`はPython分岐、`.yaml`/`.yml`はYAML分岐、`.sh`または実行可能ビットとシバンで判定した
シェルスクリプトはシェル分岐、それ以外の拡張子は素通り扱いで生の行数のみを数える）。
標準出力に`root`（渡した引数そのもの。ディレクトリを渡した場合はそのディレクトリパス）
ごとの集計、`--csv`を渡すと1ファイル1行のCSVに追記する（既存ファイルがあればヘッダを
付けずに行だけ追記する。**同じ引数で再実行すると行が重複する**——重複を避けたい時は
再実行前に`--csv`で指定した出力ファイルを削除してから作り直すこと）。

出力列（CSV）: `label, root, path, kind, lines, code_lines, docstring_lines, comment_lines,
blank_lines, items, symlink_target, syntax_error, tokenize_failed`。
`kind`は`python`/`yaml`/`shell`/`symlink`/その他拡張子。`items`はPythonなら**最上位（行頭、
インデントなし）の**`def`/`class`の数（メソッドや関数内のネストしたdef/classは数えない）、
YAMLなら葉の数、シェルなら`NAME=value`形式の代入の数。

### 比べる時の決まり（両側で同じ規則を使う）

- 主指標は **`code_lines`の合計**（Pythonの`code`、YAML/シェルの`config`。docstring・
  コメント・空行を含まない）。「実コード＋実設定」として、言語をまたいで合算してよい
  （両側とも同じ規則で数えているため）。
- 副指標として`docstring_lines`と`comment_lines`を別に出す。「行数の差の何割がdocstringか」
  を示す時は `docstring_lines / lines` の比率を両側で並べる。
- `items`（YAML葉の数・Python最上位def/class数・シェル代入数）は「設定/構造の複雑さ」の別指標。
  行数と混同しない。

## Pythonのdocstring判定（ast、行頭の引用符という近似は使わない）

docstringは「モジュール・クラス・関数（async含む）の本体の最初の文が、裸の文字列定数式
（`ast.Expr(ast.Constant(str))`）であるもの」という、Python自身が`__doc__`を設定する条件と
同じ規則で判定する。行範囲は`ast`ノードの`lineno`〜`end_lineno`（複数行docstringを完全に
カバーする）。

### 対応している/していないケース

| ケース | 扱い | 理由 |
|---|---|---|
| 複数行docstring | 開始行から終了行まで全てdocstring | `end_lineno`を使う（1行目だけ見る近似ではない） |
| f文字列がモジュール/クラス/関数の最初の文（例: `f"""..."""`） | **docstringと判定しない**（code） | f文字列は`ast.JoinedStr`であり`ast.Constant`ではない。実際のPythonでも裸のf文字列文は`__doc__`を設定しない（本物のdocstringになれない）ため、意図的に除外している |
| docstringの直後に同じ物理行でコードが続く（例: `"""doc"""; x = 1`） | **行全体をdocstringとして数える**（`x = 1`の分は別カテゴリに割らない） | 本ツールは行単位（1行=1カテゴリ）の粒度。半分だけdocstringという分類は無い。稀なケースであり、行単位ツールの既知の近似として明記する |
| 関数/クラス本体の**最初の文でない**普通の文字列リテラル文（例: 関数の3番目の文が複数行の文字列） | docstringと判定しない（code、または後述のtokenize次第でcomment扱いにはならない） | astは各スコープの`body[0]`だけを見る |
| 構文エラーのファイル | `docstring_lines`は空集合、`syntax_error=True`をCSVに残す | `ast.parse`が失敗した時点でdocstring判定を諦める。呼び出し側は`syntax_error`列を見て、その行の内訳が「comment/blankのみ判定できた近似」であることを知る |

## コメント判定（tokenize、行頭「#」という近似は使わない）

コメントは「その行に含まれる“意味のある”トークンが`COMMENT`だけである」ことを`tokenize`で
判定する（`NEWLINE`/`NL`/`INDENT`/`DEDENT`/`ENCODING`/`ENDMARKER`は無視）。これにより:

- 純粋なコメント行（`# ...`のみ）→ comment
- コード＋行末コメント（`y = 1  # note`）→ **code**（行に`NAME`/`OP`等の実トークンがあるため、
  「コメントのみ」の条件を満たさない。半分だけコメントという分類は無い）
- **複数行文字列（docstringでない普通の文字列）の中身が、たまたま`#`で始まる行** →
  **comment誤判定を防ぐ**。その行は`STRING`トークンの一部であり`COMMENT`トークンでは
  ないため、「コメントのみ」の条件を満たさず、正しく非コメント（code）として扱われる。
  これは`s.strip().startswith("#")`という素朴な行頭チェックでは避けられない誤判定であり、
  本ツールが`tokenize`を使う理由そのもの。
- `tokenize`自体が失敗した場合（`ast`は通っても`tokenize`が例外を出す稀なケース）は
  `tokenize_failed=True`をCSVに残し、素朴な`行頭が#`判定にフォールバックする
  （フォールバックした事実は隠さず列に残す）。

**YAML・シェルのコメント判定は素朴な「行頭が#」のままである**（既知の限界）。YAML/シェルの
文法にはPythonの`tokenize`に相当する標準ライブラリが無く、文字列中の`#`とコメントの`#`を
厳密に区別するには各言語のパーサが要る。実務上、YAML/シェルの設定ファイルで文字列値の中に
行頭`#`が来るケースは稀（値は多くの場合クォートされ、行頭に来ない）ため、この近似を明示した
上で採用している。

## YAML/シェルの内訳

- YAML: `config`（実データ行）/`comment`（行頭`#`）/`blank`。加えて`items`（葉の数、
  `pyyaml`必須。無い場合は`RECIPE_SIZE_ALLOW_YAML_FALLBACK=1`で正規表現の近似に
  フォールバックできるが、既定では黙って近似しない — 間違った項目数を静かに出すより
  止まる方を選ぶ）。空の辞書/リスト/`null`は1項目として数える（消えて0件になるのを防ぐ）。
- シェル: `config`/`comment`/`blank`。`items`は`NAME=value`形式の代入行の数（簡易な指標、
  関数定義や複雑な代入は数えない）。

## 読み取り専用の原則

対象ファイルの読み取りのみ。`--repo`モードは`git show <rev>:<path>` / `git ls-tree`のみ
（書き込み・fetch・checkoutは一切しない）。`--files`モードは通常のファイル読み込みのみ。
どのリポジトリ・どの言語混在プロジェクトでも使えるよう、特定プロジェクト固有の値
（パス・commit hash等）はスクリプトに埋め込まず、常に引数で渡す。

## 検証（このスキル作成時に実施した再現テスト）

1. **再現テスト（元の道具の公開出力との突合）**: `/Users/somekimasao/Documents/espnet/espnet2_vs_espnet3_ease/recipe_size.csv`
   （`recipe_size_breakdown.py`で作成済み、`upstream/master`時点）の値を、本スキルの
   `line_breakdown.py`で**5行**再現し、全て完全一致した:
   - `espnet3/systems/tts/system.py`: lines=530, code=278, docstring=177, comment=25, blank=50, items=1 — 一致
   - `espnet3/systems/base/system.py`: lines=357, code=206, docstring=108, comment=7, blank=36, items=1 — 一致
   - `egs2/TEMPLATE/tts1/tts.sh`: lines=1335, code=1027, comment=159, blank=149, items=80 — 一致
   - `egs2/TEMPLATE/tts1/cmd.sh`: lines=110, code=33, comment=57, blank=20, items=1 — 一致
   - `egs2/TEMPLATE/tts1/path.sh`: lines=23, code=13, comment=4, blank=6, items=1 — 一致
2. **手作りの機能テスト**（`tests/fixture_edge_cases.py` + `tests/test_line_breakdown.py`）:
   モジュール/クラス/関数docstring（複数行含む）、docstring直後に同じ行でコードが続くケース、
   f文字列（docstringと誤認されないこと）、実コメント行、行末コメント付きコード行
   （コメント単独ではないこと）、docstringでない複数行文字列の中の「#」で始まる行
   （コメントと誤認されないこと）、YAML/シェルの内訳・葉の数、を21件のアサーションで確認。
   `python3 skills/shogun-ast-line-breakdown/tests/test_line_breakdown.py`で実行、
   全件PASS（pyyamlが必要、無い環境では`pyyaml`が入ったpythonを使うこと）。

## 品質ルール

- docstring判定は必ず`ast`（`body[0]`が裸の文字列定数式かどうか）で行う。「行頭が引用符」の
  文字列チェックで代替しない（複数行docstringを見落とし、通常の文字列リテラル文を
  誤検出するため）。
- コメント判定は`tokenize`で行う（Pythonのみ。YAML/シェルは素朴な行頭`#`判定、既知の限界と
  して明記済み）。
- 比較時は両側（例: espnet2側とespnet3側）を必ず同じ規則・同じ道具で数える。片側だけ手で
  数え直したり、規則を変えたりしない。
- 構文エラー・tokenize失敗のファイルは`syntax_error`/`tokenize_failed`列で明示し、
  その行の内訳が近似であることを黙って隠さない。

## File Structure

```
skills/shogun-ast-line-breakdown/
├── SKILL.md                          # 本ファイル
├── scripts/
│   └── line_breakdown.py             # 汎用の道具（--repo/--rev/--paths または --files、
│                                      #   プロジェクト固有値なし）
└── tests/
    ├── fixture_edge_cases.py         # 手作りの検証用ファイル（docstring/comment/f文字列等）
    └── test_line_breakdown.py        # 21件のアサーション（pyyaml必須）
```
