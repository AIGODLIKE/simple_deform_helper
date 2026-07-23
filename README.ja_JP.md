# シンプル変形ヘルパー V2

[English](README.md) · [简体中文](README.zh_HANS.md) · [한국어](README.ko_KR.md)

**Simple Deform Helper V2** は Blender 用の非破壊ケージ変形ワークフローです。Bend、Twist、Taper、Stretch を 1 つのケージで組み合わせ、変形レイヤーの順序、連結ケージ、上下端の個別編集をリアルタイムに管理できます。

![機能比較](docs/simple_deform_helper_v2_comparison.svg)

## 主な機能

- 1 つのケージで Bend / Twist / Taper / Stretch を組み合わせ、レイヤー順をドラッグして変更。
- セグメント、間隔、自動再接続、継ぎ目スケール同期に対応した連結ケージ。
- 上端と下端の長さ、スケール、オフセットを個別に編集。オブジェクト境界制限にも対応。
- 6 面の Bend Trend、形状別コントローラー、ホバーツールチップ。
- Geometry Nodes による非破壊処理と Blender のモディファイアスタックの共存。
- 英語、簡体字中国語、日本語、韓国語の UI 翻訳。

## クイックスタート

1. Object Mode で Mesh、Curve、Surface、または Text を選択。
2. 3D ビューポートのサイドバーで **Simple Deformer V2** を開く。
3. **Add Cage Deform** をクリックし、変形レイヤーを追加して順序を調整。
4. 単一ケージは **Align & Fit**、連結ケージは **Align & Fit Chain** を使用。

## インストール

GitHub Release から `simple_deform_helper-2.0.0.zip` をダウンロードし、**Edit > Preferences > Get Extensions > Install from Disk** でインストールしてください。

比較図は主要 DCC の典型的なワークフローを要約したもので、完全な機能同等性を主張するものではありません。
