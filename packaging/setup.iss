; JARVIS GUI 安装包（Inno Setup 6+）
;
; 编译：在 packaging\ 目录运行 Inno Setup 的 ISCC
;   ISCC packaging\setup.iss
; 产物：
;   packaging\output\Jarvis-{ver}-setup.exe      安装程序（onedir 产物需先经 sign_release.ps1 签名）
;
; 设计约定（spec 打包章节）：
; - 安装目录 = {autopf}\Jarvis（Program Files，只读）——首启全部用户写入走
;   %APPDATA%\Jarvis 与 .jarvis（与安装目录分离），升级/重装不覆盖用户数据；
; - 卸载保留 %APPDATA% 与 .jarvis（用户数据不随卸载丢失，卸载页提示可选清理）。

#define MyAppName "Jarvis"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "JARVIS"
#define MyAppExeName "gui_main.exe"
; 相对 packaging\ 的 Nuitka onedir 产物目录（build_gui.ps1 输出）
#define DistDir "..\dist\jarvis-gui"

[Setup]
AppId={{8F4C2A61-0A57-4E2B-9C1D-7B3E5A6F8C9D}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\Jarvis
DefaultGroupName={#MyAppName}
DisableDirPage=no
; 安装到 Program Files 需管理员；用户数据零写入（下方 [Files] 仅 {app}）
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=output
OutputBaseFilename=Jarvis-{#MyAppVersion}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
UninstallDisplayIcon={app}\{#MyAppExeName}
; 升级前关闭正在运行的实例（防文件锁）
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; 只写 {app}（Program Files 只读安装目录）；%APPDATA%/.jarvis 由应用首启自建
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall

; 卸载时可选清理用户数据（勾选才删，默认保留；JARVIS_HOME 自定义路径不在清理范围）
[Tasks]
Name: "cleandata"; Description: "删除用户数据（%APPDATA%\Jarvis 与默认 .jarvis）"; Flags: unchecked

[Delete]
Source: "{userappdata}\Jarvis\*"; Tasks: cleandata; Type: filesanddirs
Source: "{userappdata}\Jarvis"; Tasks: cleandata; Type: dirs
Source: "{userprofile}\.jarvis\*"; Tasks: cleandata; Type: filesanddirs
Source: "{userprofile}\.jarvis"; Tasks: cleandata; Type: dirs
