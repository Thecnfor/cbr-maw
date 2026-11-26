; CBR-MAW · Windows 安装器（Inno Setup 6）
; 用法：iscc packaging/windows/CBR-MAW.iss /DAppVersion=0.1.0
; 前提：先构建出 windows/ 与 sidecar 可执行体（见 packaging/build.sh）

#define AppName "CBR-MAW"
#define AppPublisher "CBR-MAW"
#define AppExeName "CBR-MAW.exe"

[Setup]
AppId={{7C4E5F1A-9D2B-4E6C-8A11-3F5C2D9B7E40}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
OutputBaseFilename=CBR-MAW-{#AppVersion}-setup
OutputDir=..\..\dist
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; 未签名发布（D8）：用户需手动放行 SmartScreen 提示，README 已写明
SignTool=
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "autostart"; Description: "开机自启（托盘常驻后台抓取）"; GroupDescription: "附加任务:"; Flags: unchecked
Name: "icon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"; Flags: unchecked

[Files]
; Flutter 桌面产物
Source: "..\..\build\windows\x64\runner\Release\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\build\windows\x64\runner\Release\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; sidecar（Go collector + Rust kernel）
Source: "..\sidecars\collector.exe"; DestDir: "{app}\sidecars"; Flags: ignoreversion
Source: "..\sidecars\kernel.exe"; DestDir: "{app}\sidecars"; Flags: ignoreversion
; 契约与配置（只读资源根）
Source: "..\..\contracts\*"; DestDir: "{app}\contracts"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\configs\*"; DestDir: "{app}\configs"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\data\knowledge\corpus\*"; DestDir: "{app}\data\knowledge\corpus"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: icon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#AppName}"; ValueData: """{app}\{#AppExeName}"" --tray"; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#AppExeName}"; Description: "立即启动 {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 只读资源根由安装器管理；可写根（%LOCALAPPDATA%\CBR-MAW）保留用户数据
Type: filesandordirs; Name: "{app}\sidecars"
