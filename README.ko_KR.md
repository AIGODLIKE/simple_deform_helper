<div align="center">

# 세계 선도 Simple Deform Helper V2

**Blender 제작을 위한 변형 워크플로: 보이는 케이지에서 구부리기, 비틀기, 테이퍼, 늘리기를 조합합니다.**

[![2.4.6 다운로드](https://img.shields.io/badge/Download-2.4.6-2ea44f?style=for-the-badge)](https://github.com/AIGODLIKE/simple_deform_helper/releases/download/v2.4.6/simple_deform_helper-2.4.6.zip)
[![Blender 5.0+](https://img.shields.io/badge/Blender-5.0%2B-F5792A?style=for-the-badge&logo=blender&logoColor=white)](https://www.blender.org/download/)

[English](README.md) · [简体中文](README.zh_HANS.md) · [日本語](README.ja_JP.md) · [릴리스](https://github.com/AIGODLIKE/simple_deform_helper/releases) · [버그 신고](https://github.com/AIGODLIKE/simple_deform_helper/issues/new?template=bug_report.yml)

</div>

V2는 케이지로 변형이 발생하는 **위치**, 뷰포트 핸들로 바뀌는 **내용**, 레이어 목록으로 평가되는 **순서**를 한눈에 보여 줍니다.

![Simple Deform Helper V2 워크플로](docs/workflow_overview.ko_KR.svg)

## V2가 강한 이유

| 제작 문제 | V2의 해답 |
|---|---|
| 복합 변형 | 하나의 **표준형** 케이지에서 구부리기, 비틀기, 테이퍼, 늘리기를 순서대로 조합하고 일시 우회, 애니메이션, 실시간 확인을 지원합니다. |
| 긴 연속 형태 | **체인 케이지**가 2-8개 세그먼트, 간격, 자동 재연결, 공유 접합부 스케일 동기화를 제공합니다. |
| 비대칭 끝단 | 상단과 하단의 길이, X/Z 스케일, X/Z 오프셋을 독립적으로 편집합니다. 중심 대칭을 강제하지 않습니다. |
| 방향 선택 | **구부리기 경향**이 여섯 면마다 가로/세로 방향을 제공하고 축 변경 후 **정렬 및 맞춤**을 실행합니다. |
| 인수인계 | Geometry Nodes 단계가 Blender 수정자 스택에 남아 확인과 애니메이션이 가능합니다. |

![Maya, 3ds Max, MODO, Cinema 4D와의 워크플로 비교](docs/simple_deform_helper_v2_comparison.ko_KR.svg)

비교 이미지는 기능을 한 워크플로에 집중하는 방식을 보여 주며, 다른 소프트웨어가 개별 결과를 만들 수 없다는 뜻은 아닙니다.

## 설치

1. [Release의 `simple_deform_helper-2.4.6.zip`](https://github.com/AIGODLIKE/simple_deform_helper/releases/download/v2.4.6/simple_deform_helper-2.4.6.zip)을 받습니다. GitHub의 Source code ZIP은 사용하지 마세요.
2. Blender에서 **Edit > Preferences > Get Extensions**를 엽니다. GitHub ZIP을 설치하기 전에 **Blender Extensions** 저장소의 이전 **Simple Deform Helper**를 제거합니다. **User Default**에 **Simple Deform Helper V2**가 있다면 그대로 두세요. 이 ZIP이 같은 저장소에서 해당 버전을 교체합니다.
3. 이전 클래스가 메모리에 남지 않도록 Blender를 완전히 종료한 뒤 다시 시작합니다.
4. **Get Extensions > Install from Disk**를 열고 저장소를 **User Default**로 선택한 다음 ZIP을 지정합니다.
5. 자동으로 활성화되지 않으면 **Simple Deform Helper**를 활성화합니다.
6. 3D View에서 `N`을 누르고 **Simple Deformer V2** 탭을 엽니다.

저장소 복사본은 하나만 유지하세요. 확장 ID와 목록 이름은 계속 `simple_deform_helper`와 **Simple Deform Helper**이지만 Blender는 **Blender Extensions**와 **User Default**의 같은 ID를 서로 다른 모듈로 취급합니다. 이 버전이 기존 Blender Extensions 페이지에 게시된 뒤에는 GitHub ZIP 대신 Blender의 **Update** 기능을 사용하세요.

## 60초 첫 변형

1. Object Mode에서 Mesh, Curve, Surface 또는 Text를 선택합니다.
2. **Add Cage Deform**을 클릭합니다.
3. **Deformation Layers**에서 Bend를 선택하고 각도를 설정합니다.
4. **Cage Controls**에서 Auto 또는 `X+ / X- / Y+ / Y- / Z+ / Z-`를 고른 뒤 **Align & Fit**을 누릅니다.
5. **Bend Trend** 화살표로 방향을 고르고 주황색 핸들을 드래그합니다. `Shift`는 정밀 조정, `Ctrl`은 스냅입니다.
6. 끝나면 **Return to Object**를 누릅니다.

단면을 옆으로 미는 작업에는 **Add Shear Cage**를 사용합니다. 청록색 끝면 핸들은 평면에서 자유롭게 드래그하며 `Alt`는 케이지 X, `Shift`는 케이지 Z, `Ctrl`은 스냅입니다. **Add FFD Cage**는 `2x2x2`(8점)로 시작하며 각 축은 `2-6`, 최대 `6x6x6`입니다. **Box Select** 또는 All/None/Invert로 점 그룹을 만들고 선택한 점을 함께 드래그할 수 있습니다. **Hollow FFD**는 내부 점을 숨기고 변형에서 제외합니다. 두 전용 케이지는 체인화하거나 세분화할 수 없습니다.

애니메이션은 케이지 패널의 **Insert Keys**를 사용하세요. 현재 레이어 매개변수, 끝단 형태, Shear/FFD, 케이지 크기와 변환을 키로 기록하며 **Delete Keys**는 현재 프레임의 키를 삭제합니다.

변형이 각지면 변형 축 방향의 지오메트리 세그먼트를 늘리세요.

## 여러 오브젝트를 하나의 변형으로 병합

1. Mesh, Curve, Surface, Text, Metaball, Curves 또는 Point Cloud 오브젝트를 두 개 이상 선택합니다.
2. **Simple Deformer V2** 패널 맨 위의 **Merge Selected for Deform**을 클릭합니다. 비메시 원본은 메시로 변환되며 원본 수정자 변화는 병합 결과에 실시간 반영됩니다.
3. 생성된 병합 오브젝트에 **Cage Deform**, 체인 케이지 또는 다른 수정자를 추가합니다.
4. 병합 결과의 보이는 부분을 더블클릭하면 해당 원본 오브젝트가 선택됩니다. 원본을 편집하는 동안 앞쪽 와이어로 표시됩니다.
5. 원본을 편집하는 동안 파란색 미리보기가 병합 오브젝트의 전체 수정자 스택(케이지 포함)을 거친 최종 상태를 보여 줍니다. 애드온 환경설정의 **Show Final Merged State While Editing Sources**에서 끌 수 있습니다.
6. **Add Cage to Final Source**는 병합 오브젝트의 현재 수정자 스택을 거친 선택 원본의 최종 상태에 새 케이지를 맞춥니다. 원본 인덱스로 마스킹되므로 다른 병합 원본은 변형되지 않습니다.
7. **Merged Sources**는 스크롤 가능한 Blender 기본 목록입니다. 행을 클릭해 원본을 전환할 수 있습니다. 뷰포트에서는 다른 부분을 더블클릭해 전환하고, 빈 곳 더블클릭, `Esc`, 오른쪽 클릭으로 모달 편집을 종료합니다.
8. **Return to Merged Object**로 원본을 다시 숨기고 병합 오브젝트로 돌아갑니다. 연결 해제 버튼은 병합을 제거하고 원래 표시 상태를 복원합니다.

케이지 변형 뒤에도 면 원본 인덱스가 유지되므로 구부리기, 비틀기, 테이퍼, 늘리기 후에도 원본을 다시 찾을 수 있습니다.

## 한 케이지에서 복합 변형

레이어는 위에서 아래로 실행됩니다.

```text
Object input -> Bend -> Twist -> Taper -> Stretch -> Independent Ends -> output
```

**Add Deformation**으로 레이어를 추가하고 위/아래 화살표로 순서를 바꿉니다. 눈 아이콘은 일시 우회, `X`는 삭제, **Expand All**은 모든 레이어를 펼칩니다. 순서를 바꿔도 셋업을 다시 만들 필요가 없습니다.

## 체인 케이지

### 새 체인 만들기

1. **Add Chained Cages**를 클릭합니다.
2. 수량(`2-8`), **Chained** / **Independent**, **Gap**, 축을 설정합니다.
3. 연속 파이프 형태에는 **Auto Reconnect**와 **Sync Shared End Scale**을 켭니다.
4. **Show Other Cages**로 비활성 케이지를 표시하고 직접 선택합니다.
5. 축을 바꾼 뒤 **Align & Fit Chain**을 사용합니다.

### 기존 케이지 분할과 일괄 편집

단일 표준형 케이지에서 **Subdivide to Chained Cages**를 실행하면 외부 범위와 상/하단 스케일 및 오프셋 형태를 유지한 체인이 만들어집니다. **Bottom** Origin을 권장하며 다른 Origin에는 근사 오차 경고가 표시됩니다. Bend/Twist 값과 간격은 전체 범위에 맞게 분배됩니다. **Batch Edit**는 끝단, 간격, 변형값과 표시를 실시간 미리보기하며 취소하면 복원합니다.

체인 내부 경계는 겹치지 않고 의도적인 간격을 유지할 수 있습니다. 공유 접합부만 동기화되며 양쪽 외부 끝단은 독립적입니다.

## 컨트롤러 빠른 참조

| 색상 / 모양 | 동작 |
|---|---|
| 주황색 이중 화살표 | Bend 각도. `Shift` 정밀, `Ctrl` 스냅. |
| 큰 보라색 호 | Twist 각도. 중심을 기준으로 드래그. |
| 호박색 / 녹색 | Taper / Stretch 계수. |
| 노란 상단 / 호박색 하단 | 한쪽 경계만 이동. 오브젝트 경계 제한 가능. |
| 청록 상단 왕관 / 녹색 하단 받침 | 한쪽 단면 편집. `Alt`는 화면 X, `Shift`는 화면 Y, `Alt+Shift`는 자유 이동. |
| 청록색 4방향 핸들 | Shear. 끝면에서 드래그하며 `Alt`는 X, `Shift`는 Z, `Ctrl`은 스냅. |
| 분홍 / 청록 FFD 점 | 선택한 점을 함께 이동. Box Select와 All/None/Invert 지원. |
| 빨강 / 초록 화살표 | Bend Trend. `Ctrl`로 선택기를 열린 상태로 유지. |
| RGB 다이아몬드 / 링 | 양 / 음 축 전환. |

핸들 위에 마우스를 올리면 기능명이 표시됩니다. 관리용 Empty는 **Simple Deform Controls** 컬렉션에 모이며 필요할 때만 표시됩니다.

## 호환성과 제한

- Blender 5.0.0 이상.
- 케이지 대상: Mesh, Curve, Surface, Text.
- Lattice: **Add Simple Deform (Legacy)**만 제공하며 케이지 미지원 안내를 표시합니다.
- 케이지는 Geometry Nodes, Legacy는 Blender 기본 Simple Deform을 사용합니다.
- UI 언어: English, 简体中文, 日本語, 한국어.
- 케이지 값, 레이어, 변환, 표시 상태, Legacy 속성을 애니메이션할 수 있습니다.

## 문제 해결

| 증상 | 확인 |
|---|---|
| 탭이 보이지 않음 | 확장을 활성화하고 3D View에서 `N`을 누릅니다. 업데이트 후 Blender를 재시작하세요. |
| 변형되지 않음 | Object Mode에서 지원 대상을 선택하고 **Align & Fit**을 실행합니다. |
| 체인이 어긋남 | **Auto Reconnect**, **Reconnect Chain**, Gap, 접합부 스케일을 확인합니다. |
| 구부리기가 거침 | 변형 축 방향의 지오메트리 세그먼트를 늘립니다. |
| Lattice에 케이지를 추가할 수 없음 | 의도된 제한입니다. Legacy를 사용하세요. |

## 피드백과 라이선스

[Issue template](https://github.com/AIGODLIKE/simple_deform_helper/issues/new?template=bug_report.yml)에 Blender/확장 버전, OS, GPU, 재현 단계, 콘솔 로그, 최소 `.blend` 파일을 첨부해 주세요. Simple Deform Helper V2는 [`blender_manifest.toml`](blender_manifest.toml)에 선언된 **GPL-3.0-or-later**입니다.
