# ConfereVídeo · Guia rápido

Conferência da separação por vídeo. O sistema acompanha a mão do operador entre **prateleira → leitor → caixa**, ouve o **bipe** e grava **só os trechos com erro**.

| Erro detectado | Como identifica |
|---|---|
| Colocou na caixa sem passar no leitor | A mão foi da prateleira direto para a caixa |
| Colocou em outra caixa | A mão soltou o item numa caixa vizinha |
| Passou no leitor, mas não bipou | Passou pelo leitor e o microfone não ouviu bipe |
| Bipe duplo para um item | Ouviu 2 ou mais bipes para um item |

---

## 1. Instalar (uma vez)

1. Instale o **Python 3.11 ou 3.12** (python.org) e marque **"Add python.exe to PATH"**.
2. Dois cliques em **`INSTALAR.bat`**.
3. Abra pelo atalho **ConfereVideo** que aparece na área de trabalho. Também dá para abrir pelo `ConfereVideo.vbs`.

A IA já vem dentro da pasta, então não precisa de internet depois de instalado.

No fim da instalação o programa **verifica o PC** sozinho (componentes, IA, câmera, microfone e conexão com o Microsoft 365) e abre o resultado no Bloco de Notas (`diagnostico.txt`), com o que falta fazer. Para verificar de novo: **`VERIFICAR_PC.bat`** ou **Configurações > Verificar este PC**.

## 2. Ver funcionando antes de instalar a câmera

Tela **Câmera ao vivo** → **▶ Ver demonstração**. O sistema roda num vídeo de demonstração de um posto de separação de cigarros e mostra os erros sendo gravados na hora. A demonstração usa as próprias áreas e não mexe nas suas configurações. O resultado aparece em **Relatórios** como "Demonstração".

## 3. Marcar as áreas do posto (uma vez por posição de câmera)

Tela **Áreas do posto** → *Marcar usando um vídeo* ou *Marcar usando a câmera ao vivo*:

| Tecla | Área |
|---|---|
| `1` | Prateleira, de onde pega (pode marcar mais de uma com `N`) |
| `2` | Leitor, a região onde o item passa para bipar |
| `3` | Caixa do posto, só a **abertura** da caixa |
| `4` | Outras caixas (opcional) |
| `5` | Área do operador (opcional, ajuda se aparece mais gente) |

Clique nos cantos, `Z` desfaz e **ENTER** salva.

## 4. Usar

### Câmera ao vivo
Grava **só os erros** enquanto a operação acontece. O turno não fica guardado.
- **Câmera**: `0`, `1`… para câmera USB ou **GoPro no modo webcam**; `rtsp://…` para câmera IP.
- **Microfone**: o do PC/webcam, perto do leitor. Use **Testar bipe (10 s)** e bipe 3 ou 4 vezes.
- **Iniciar**: cada erro aparece na lista na hora, com aviso sonoro. Dê duplo clique para ver o recorte.
- **Usar um vídeo como câmera**: toca um vídeo gravado como se fosse a câmera ao vivo (útil para testar um vídeo seu).

### Vídeos gravados
Adicione os vídeos ou a **pasta da GoPro** e clique em **Analisar**. Os arquivos que a GoPro divide (GH01…, GH02…) entram na ordem certa.

### Relatórios
Cada sessão (ou turno) gera uma pasta em `resultados\` com:
- `relatorio.pdf`: o relatório do turno em PDF (vai anexo no e-mail do gestor)
- `relatorio.html`: indicadores, erros por tipo e por hora, e **os recortes para assistir**. Para PDF, use Imprimir → Salvar como PDF.
- `recortes\NNNN_tipo_original.mp4` (com som) e `NNNN_tipo_marcado.mp4` (com as marcações)
- `fotos\` e `erros.csv` (Excel)

### Configurações
Nome da empresa, unidade, posto e **logo** (saem no relatório), quais erros verificar, sensibilidade do bipe, segundos antes e depois no recorte e precisão da IA.

## 5. Automação (o posto funcionando sozinho)

Tela **Automação**:
- **Abrir quando o PC ligar**: o programa abre sozinho e já liga a câmera ao vivo.
- **Horários de troca de turno** (ex.: `06:00, 14:20, 22:35`): em cada horário o relatório do turno é fechado (HTML + **PDF**), o resumo é enviado e o próximo turno começa sozinho.
- **Avisar câmera sem imagem**: se a câmera parar, chega alerta no Teams e por e-mail; o programa tenta reconectar sozinho.
- **Guardar recortes por N dias**: apaga sozinho as sessões antigas (LGPD).
- **Não deixar o PC suspender** enquanto a câmera está ligada.

## 6. Microsoft 365 (SharePoint, Teams, Outlook, Power Automate, Power Apps)

Tela **Microsoft 365**. Cada erro vira item numa lista do SharePoint (com foto e recorte), aparece no Teams, e o gestor recebe o resumo de cada turno por e-mail com o PDF. Os supervisores fazem a tratativa num app do Power Apps (erro confirmado ou falso alarme, orientação dada, operador).

1. Preencha o site do SharePoint e os e-mails e clique em **Gerar fluxos do Power Automate…**
2. Importe os 4 fluxos no Power Automate, rode o fluxo 1 (cria as listas) e cole no programa a URL do fluxo 2.
3. **Testar envio**: chega um cartão no Teams.
4. Monte o app colando as telas da pasta `Microsoft365\PowerApps`.

O passo a passo completo está em **`Microsoft365\GUIA_MICROSOFT_365.html`** (botão **Abrir guia**). Se a internet cair, os envios esperam na pasta `fila_envio` e saem sozinhos depois.

## 7. Câmera: como posicionar

- **Alta e na diagonal**, vendo ao mesmo tempo o operador (braços e mãos), a prateleira, o leitor e a caixa.
- O ideal é o leitor ficar **entre a prateleira e a caixa**, para o braço não cruzar na frente do corpo.
- Ao marcar as **outras caixas**, inclua também o espaço logo acima da abertura, por onde a mão entra.
- Câmera **fixa**. Se mudar de lugar, marque as áreas de novo.
- **GoPro**: lente **Linear**, **1080p 30 fps**, "Alta eficiência" (HEVC) **desligado**, ligada na tomada.

## 8. Quando algo não sai certo

| Situação | O que fazer |
|---|---|
| Acusa "sem leitor", mas passou | Aumente um pouco a área do leitor |
| Acusa que colocou na caixa só de passar por cima | Marque a caixa mais justa (só a abertura) |
| Não ouve o bipe | Aproxime o microfone e aumente a sensibilidade em Configurações |
| Conta barulho como bipe | Diminua a sensibilidade |
| Não reconhece a mão | Configurações → Precisão "Precisa" (melhor com placa de vídeo) |
| O programa fechou | Veja o arquivo `erro.log` na pasta do programa |
| Não sei o que está faltando | Rode o `VERIFICAR_PC.bat` e mande o `diagnostico.txt` para o suporte |
| Não chega nada no Teams | Tela Microsoft 365 > **Testar envio** e veja a mensagem; o histórico fica em `fila_envio\envios.log` |

## Limitações

- O sistema segue a **mão**, não o pacote. Mão vazia indo da prateleira para a caixa pode gerar alerta.
- Mão escondida atrás de caixa ou do corpo: aquele momento não é avaliado.
- É uma ferramenta de **apoio**: confirme cada recorte antes de qualquer tratativa.

## LGPD

Use com ciência da gestão e dos operadores. O sistema não faz reconhecimento facial e grava só os trechos com erro. Os recortes servem para orientação e melhoria do processo.
