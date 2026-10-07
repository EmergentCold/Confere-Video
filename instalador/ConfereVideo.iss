; Instalador do ConfereVídeo (Inno Setup 6). Montado pelo instalador\montar.ps1.
; Instala na pasta do usuário (sem pedir administrador), para o programa poder gravar
; config.yaml, areas.yaml, resultados\ e fila_envio\ na própria pasta, como na versão com Python.

#ifndef Versao
  #define Versao "1.0.0"
#endif

[Setup]
AppId={{6E0F7C1A-2B7D-4C55-9A3E-4E1B7A5C0D21}
AppName=ConfereVídeo
AppVersion={#Versao}
AppPublisher=Emergent Cold
DefaultDirName={autopf}\ConfereVideo
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=ConfereVideo_Instalador
SetupIconFile=..\icone.ico
UninstallDisplayIcon={app}\ConfereVideo.exe
UninstallDisplayName=ConfereVídeo
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"

[Files]
Source: "..\dist\ConfereVideo\*"; DestDir: "{app}"; Excludes: "config.yaml"; Flags: ignoreversion recursesubdirs createallsubdirs
; a configuração do posto não é trocada ao atualizar o programa
Source: "..\dist\ConfereVideo\config.yaml"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{autoprograms}\ConfereVídeo"; Filename: "{app}\ConfereVideo.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\ConfereVídeo"; Filename: "{app}\ConfereVideo.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\ConfereVideo.exe"; Description: "Abrir o ConfereVídeo"; Flags: nowait postinstall skipifsilent
