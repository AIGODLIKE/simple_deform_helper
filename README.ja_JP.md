<div align="center">

# 世界をリードする Simple Deform Helper V2

**Blender の制作向け変形ワークフロー。見えるケージで曲げ、ねじり、テーパー、伸縮を組み合わせます。**

[![2.4.6 をダウンロード](https://img.shields.io/badge/Download-2.4.6-2ea44f?style=for-the-badge)](https://github.com/AIGODLIKE/simple_deform_helper/releases/download/v2.4.6/simple_deform_helper-2.4.6.zip)
[![Blender 5.0+](https://img.shields.io/badge/Blender-5.0%2B-F5792A?style=for-the-badge&logo=blender&logoColor=white)](https://www.blender.org/download/)

[English](README.md) · [简体中文](README.zh_HANS.md) · [한국어](README.ko_KR.md) · [リリース](https://github.com/AIGODLIKE/simple_deform_helper/releases) · [バグ報告](https://github.com/AIGODLIKE/simple_deform_helper/issues/new?template=bug_report.yml)

</div>

V2 は、変形が起きる**場所**をケージで、変わる**内容**をビューポートハンドルで、評価される**順序**をレイヤーリストで確認できるようにします。

![Simple Deform Helper V2 ワークフロー](docs/workflow_overview.ja_JP.svg)

## V2 の強み

| 制作上の課題 | V2 の答え |
|---|---|
| 複合変形 | 1 つの**標準型**ケージに Bend、Twist、Taper、Stretch を順序付きで追加し、並べ替え・一時バイパス・アニメーション・ライブ確認。 |
| 長い連続形状 | **チェーンケージ**で 2-8 分割、間隔、自動再接続、共有継ぎ目スケール同期。 |
| 非対称な端部 | 上下端の長さ、X/Z スケール、X/Z オフセットを個別に編集。中心対称を強制しません。 |
| 曲げ方向の選択 | 六面それぞれに横・縦 2 種類の **Bend Trend**。軸変更後は **Align & Fit**。 |
| 引き継ぎ | Geometry Nodes のステージをモディファイアスタックに残し、確認・アニメーション可能。 |

![Maya、3ds Max、MODO、Cinema 4D とのワークフロー比較](docs/simple_deform_helper_v2_comparison.ja_JP.svg)

比較図は機能の集中度と一般的な制作フローを示すもので、他のソフトウェアが個別の結果を再現できないという主張ではありません。

## インストール

1. [Release の `simple_deform_helper-2.4.6.zip`](https://github.com/AIGODLIKE/simple_deform_helper/releases/download/v2.4.6/simple_deform_helper-2.4.6.zip) をダウンロードします。Source code ZIP は使用しないでください。
2. Blender の **Edit > Preferences > Get Extensions** を開きます。GitHub ZIP を使う前に、**Blender Extensions** リポジトリの旧 **Simple Deform Helper** をアンインストールします。**User Default** に **Simple Deform Helper V2** がある場合は残してください。この ZIP が同じリポジトリ内で置き換えます。
3. 古いクラスをメモリから消すため、Blender を完全に終了して再起動します。
4. **Get Extensions > Install from Disk** を開き、リポジトリに **User Default** を選んで ZIP を指定します。
5. 自動で有効にならない場合は **Simple Deform Helper** を有効にします。
6. 3D View で `N` を押し、**Simple Deformer V2** タブを開きます。

リポジトリのコピーは一つだけ残してください。拡張 ID と一覧名は `simple_deform_helper` と **Simple Deform Helper** のままですが、Blender は **Blender Extensions** と **User Default** の同じ ID を別モジュールとして扱います。この版が元の Blender Extensions ページで公開された後は、GitHub ZIP ではなく Blender の **Update** を使用してください。

## 60 秒で最初の曲げ

1. Object Mode で Mesh、Curve、Surface、または Text を選択します。
2. **Add Cage Deform** を押します。
3. **Deformation Layers** の Bend で角度を設定します。
4. **Cage Controls** で Auto または `X+ / X- / Y+ / Y- / Z+ / Z-` を選び、**Align & Fit** を押します。
5. **Bend Trend** の矢印をクリックして向きを選び、オレンジのハンドルをドラッグします。`Shift` は精密、`Ctrl` はスナップです。
6. 終了時は **Return to Object** を押します。

断面を横へスライドする場合は **Add Shear Cage** を使用します。シアンの端面ハンドルは平面内を自由にドラッグでき、`Alt` はケージ X、`Shift` はケージ Z、`Ctrl` はスナップです。**Add FFD Cage** は `2x2x2`（8 点）から始まり、各軸は `2-6`、最大 `6x6x6` です。**Box Select** または All/None/Invert で点をまとめ、選択点を同時にドラッグできます。**Hollow FFD** は内部点を非表示にして変形から除外します。どちらもチェーン化や細分化はできません。

アニメーションにはケージパネルの **Insert Keys** を使用します。現在のレイヤーパラメータ、端部形状、Shear/FFD、ケージのサイズと変換をキー化できます。**Delete Keys** は現在フレームのキーを削除します。

低ポリゴンで曲げが粗い場合は、変形軸方向の分割数を増やしてください。

## 複数オブジェクトを一つの変形にまとめる

1. Mesh、Curve、Surface、Text、Metaball、Curves、Point Cloud を2つ以上選択します。
2. **Simple Deformer V2** パネル上部の **Merge Selected for Deform** を押します。非メッシュはメッシュへ変換され、元オブジェクトの修正子は結合結果へライブ反映されます。
3. 生成された結合オブジェクトに **Cage Deform**、チェーンケージ、その他の修正子を追加します。
4. 結合結果の表示部分をダブルクリックすると対応する元オブジェクトを選択できます。編集中は前面ワイヤーで表示されます。
5. 元を編集中は、青いプレビューが結合オブジェクトの全修正子スタック（ケージを含む）後の最終状態を表示します。アドオン設定の **Show Final Merged State While Editing Sources** で無効にできます。
6. **Add Cage to Final Source** は、結合オブジェクトの現在の修正子スタック後にある選択元の最終状態へ新しいケージをフィットします。元インデックスでマスクされるため、他の結合元は変形しません。
7. **Merged Sources** はスクロールできる標準リストです。行をクリックして元を切り替えられます。ビューポートでは別の部分をダブルクリックして切り替え、空白をダブルクリック、`Esc`、右クリックでモーダル編集を終了できます。
8. **Return to Merged Object** で元を隠して結合へ戻ります。リンク解除ボタンは結合を削除し、元の表示状態を復元します。

ケージ変形後も面のソース番号が保持されるため、曲げ、ねじり、テーパー、伸縮の後でも元オブジェクトを特定できます。

## 1 ケージで複合変形

レイヤーは上から下へ評価されます。例：

```text
Object input -> Bend -> Twist -> Taper -> Stretch -> Independent Ends -> output
```

**Add Deformation** でレイヤーを追加し、上下矢印で順番を変更します。目のアイコンは一時バイパス、`X` は削除、**Expand All** は全レイヤーを展開します。順序を変えてもセットアップを作り直す必要はありません。

## チェーンケージ

### 新しいチェーン

1. **Add Chained Cages** を押します。
2. 数（`2-8`）、**Chained** / **Independent**、**Gap**、軸を設定します。
3. 連続形状では **Auto Reconnect** と **Sync Shared End Scale** を有効にします。
4. **Show Other Cages** で非アクティブなケージを表示・選択できます。
5. 軸を変更した後は **Align & Fit Chain** を使います。

### 既存ケージの分割と一括編集

単一の標準型ケージで **Subdivide to Chained Cages** を実行すると、外側の範囲と上下端のスケール/オフセット形状を保ったチェーンになります。**Bottom** Origin を推奨し、他の Origin では近似誤差の警告を表示します。Bend/Twist の値は分割へ配分され、間隔は範囲内に制限されます。**Batch Edit** は端部、間隔、変形値、表示をライブプレビューし、キャンセルで復元します。

接続ケージの内部境界は重ならず、必要なら間隔を残せます。共有継ぎ目だけが同期され、外側の端部は独立します。

## コントローラー

| 色 / 形状 | 操作 |
|---|---|
| オレンジの矢印 | Bend 角度。`Shift` 精密、`Ctrl` スナップ。 |
| 大きな紫の円弧 | Twist 角度。中心の周りをドラッグ。 |
| アンバー / 緑 | Taper / Stretch の係数。 |
| 黄色上端 / アンバー下端 | 一方の境界だけを移動。オブジェクト境界で停止可能。 |
| シアンの上冠 / 緑の下トレイ | 一方の断面を編集。`Alt` は画面 X、`Shift` は画面 Y、`Alt+Shift` は自由移動。 |
| シアンの四方向ハンドル | Shear。端面内をドラッグし、`Alt` は X、`Shift` は Z、`Ctrl` はスナップ。 |
| ピンク / シアンの FFD 点 | 選択点をまとめて移動。Box Select と All/None/Invert に対応。 |
| 赤 / 緑の矢印 | Bend Trend。`Ctrl` で選択肢を開いたままにします。 |
| RGB の菱形 / リング | 正 / 負の軸切り替え。 |

ハンドルにカーソルを置くと機能名が表示されます。管理用 Empty は **Simple Deform Controls** コレクションにまとめられ、必要な時だけ表示されます。

## 対応範囲

- Blender 5.0.0 以降。
- ケージ：Mesh、Curve、Surface、Text。
- Lattice：**Add Simple Deform (Legacy)** のみ。ケージ非対応の案内を表示します。
- ケージは Geometry Nodes、Legacy は Blender の標準 Simple Deform を使用します。
- UI：English、简体中文、日本語、한국어。
- ケージ値、レイヤー、変換、表示状態、Legacy プロパティをアニメーション可能です。

## トラブルシューティング

| 症状 | 確認 |
|---|---|
| タブがない | 拡張を有効にし、3D View で `N` を押します。更新後は Blender を再起動します。 |
| 変形しない | Object Mode で対応オブジェクトを選択し、ステージを **Align & Fit** します。 |
| チェーンがずれる | **Auto Reconnect** と **Reconnect Chain**、Gap、継ぎ目スケールを確認します。 |
| 曲げが粗い | 変形軸方向のジオメトリ分割を増やします。 |
| Lattice にケージを追加できない | 意図した制限です。Legacy を使用してください。 |

## フィードバックとライセンス

[Issue template](https://github.com/AIGODLIKE/simple_deform_helper/issues/new?template=bug_report.yml) に Blender/拡張バージョン、OS、GPU、再現手順、コンソールログ、最小 `.blend` を添付してください。Simple Deform Helper V2 は [`blender_manifest.toml`](blender_manifest.toml) の宣言どおり **GPL-3.0-or-later** です。
