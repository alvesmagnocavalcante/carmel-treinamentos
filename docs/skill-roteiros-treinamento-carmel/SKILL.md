---
name: "roteiros-treinamento-carmel"
description: "Use quando o usuário pedir para criar, adaptar, dividir ou revisar um roteiro de vídeo de treinamento do Carmel Hotéis (narrado por avatar HeyGen, com ou sem imagens nas cenas), a partir de um tema, manual ou procedimento."
---

# Roteiros de treinamento – Carmel Treinamentos

Esta skill produz o **texto que o avatar vai falar**, com as marcações de cena quando o vídeo tiver imagens. Ela não gera o vídeo. O fluxo do portal Carmel Treinamentos é este:

1. O roteiro é salvo como documento (Google Doc, DOCX, PDF, TXT ou MD) na pasta `<Setor>/Roteiros` do Drive.
2. O portal lê o documento e o **texto falado vira a fala do avatar, exatamente como está escrito**. As marcações `[IMAGEM: ...]` e `[AVATAR]` (veja abaixo) dividem o roteiro em cenas e **não são narradas**.
3. O gestor do setor revisa e aprova. Depois da aprovação, edições feitas no Drive são ignoradas.
4. O vídeo é gerado na HeyGen (avatar e voz do setor) e publicado no catálogo.

Como o texto vai direto para a voz, o roteiro precisa estar **pronto para ser falado**: sem rascunho e sem instruções de cena **escritas em linguagem comum**. A única coisa que não é falada são as marcações oficiais da seção seguinte.

## Cenas: avatar e imagens (marcações oficiais)

Um vídeo pode alternar entre o **avatar falando** e **imagens em tela cheia** com a voz narrando (nas cenas de imagem o avatar não aparece). Isso evita um vídeo que só troca de imagem. Duas marcações, **sempre numa linha sozinha**:

- `[IMAGEM: nome-do-arquivo.png]` abre uma cena com aquela imagem. Tudo até a próxima marcação é o texto falado da cena.
- `[AVATAR]` abre uma cena com o **avatar falando**, sem imagem.
- O texto antes da primeira marcação é a cena 1 e é falado pelo avatar.
- Para animar a imagem: `[IMAGEM: nome.png | animar]` (movimento suave padrão) ou `[IMAGEM: nome.png | animar: zoom lento]`. Use `animar` só quando o usuário pedir ou quando a cena claramente ganhar com movimento. No máximo **4 cenas animadas** por vídeo. No texto "como animar", descreva só movimento de câmera ou luz, **sem citar objetos, comida, mãos ou pessoas** (citar o objeto, mesmo proibindo, faz a IA desenhá-lo).

**Regras das marcações**
- **Só use imagens que o usuário informou** (nome exato do arquivo, que fica em `<Setor>/Imagens` no Drive). **Nunca invente** nome de arquivo nem peça "uma imagem de X" que não exista. Formatos: png, jpg, jpeg, webp; até 10 MB.
- **Sem imagens informadas, não use nenhuma marcação**: o roteiro é só o texto corrido do avatar, como sempre.
- Toda marcação precisa ser seguida de texto falado. Cena sem texto é descartada.
- Um colchete que **parece** marcação mas está errado (`[IMAGEM piscina.png]`, `[AVATAR: oi]`) **bloqueia a aprovação**. Escreva exatamente `[IMAGEM: arquivo.png]` e `[AVATAR]`, uma por linha, sem texto na mesma linha.
- Depois de uma imagem, o texto seguinte continua na imagem até aparecer outra marcação. **Para o avatar voltar, é obrigatório escrever `[AVATAR]`.**

**Como intercalar (com imagens disponíveis)**
- **Abertura e fechamento são do avatar** (texto antes da primeira marcação, e um `[AVATAR]` antes do fechamento).
- Use **imagem** para mostrar e explicar: o passo prático, o ambiente, o objeto, o exemplo.
- Use **`[AVATAR]`** para o que pede presença: pontos de atenção, regras importantes, transições entre blocos, resumo e orientação final.
- Evite mais de **2 cenas de imagem seguidas** sem o avatar voltar, e cenas de imagem longas demais. Cada cena fica melhor com **300 a 700 caracteres**.
- Um mesmo roteiro pode ter, por exemplo: avatar, imagem, imagem, avatar, imagem, avatar.

Exemplo de estrutura (ilustrativo):

```
Bem-vindo ao treinamento de recepção. Hoje vamos ver o empréstimo do carregador.

[IMAGEM: balcao-recepcao.png]
Quando o hóspede pedir um carregador, cumprimente e confirme o quarto dele.

[AVATAR]
Atenção a este ponto: sempre registre o empréstimo antes de entregar.

[IMAGEM: carregador.png | animar]
Entregue o carregador e explique que a devolução é feita na recepção.

[AVATAR]
Em resumo: cumprimentar, registrar, entregar e orientar. Em caso de dúvida, procure o seu gestor.
```

## Regras técnicas (vêm do código do portal)

- **Limite: 5.000 caracteres de texto falado** por roteiro (limite da HeyGen). **As marcações não contam**, só o que é falado, somando as cenas. Acima disso o gestor não consegue aprovar.
- **Meta de tamanho:** de 1.800 a 3.500 caracteres falados, cerca de 2 a 4 minutos de fala (estimativa de ~900 caracteres por minuto). Vídeos curtos retêm mais atenção e consomem menos créditos da HeyGen. Cenas animadas gastam crédito extra.
- **Texto corrido, em parágrafos curtos.** O portal remove no início das linhas: títulos markdown (`#`), marcadores (`-`, `*`, `•`), citações (`>`) e numeração (`1.`, `2)`, `3.2`, `a)`). Por isso não use listas nem títulos: transforme tudo em frases ("Primeiro…", "Em seguida…", "Por fim…").
- **Sem tabelas.** Tabelas de DOCX são achatadas com `|` e o avatar leria isso. Converta em frases.
- **Nada que o avatar não deva falar:** sem indicações de cena ou câmera em texto comum, tempos, nomes de slide, emojis, parênteses explicativos, notas entre colchetes (além das duas marcações oficiais), URLs ou e-mails longos.
- **Escreva para o ouvido:** frases curtas (idealmente até ~20 palavras), voz ativa, uma ideia por frase. Escreva por extenso o que a voz pode ler errado: siglas pouco comuns (a primeira vez, por extenso, ou como se pronuncia), números, horários ("das oito às dezoito horas"), valores e símbolos ("por cento", "reais").
- **Cada cena de imagem deve fazer sentido sozinha com a imagem na tela**: o texto não pode depender de ver o avatar.
- Português do Brasil.

## Processo

### 1. Levantamento (só se faltar o essencial)
Não faça perguntas quando já houver tema ou material: assuma o que faltar (público = equipe do setor, tom padrão, duração dentro da meta) e gere. Pergunte apenas se não houver nem tema nem material-fonte. Pontos considerados:
- **Setor:** RH, Recepção, Governança, Alimentos & Bebidas, Lazer & Experiências ou Manutenção.
- **Tema e objetivo:** o que o colaborador deve saber ou fazer depois do vídeo.
- **Material-fonte:** procedimento, manual, política ou anotações (o usuário cola ou anexa).
- **Público:** quem assiste (novos colaboradores, equipe inteira, líderes).
- **Duração desejada**, se houver.
- **Imagens disponíveis** (nomes dos arquivos), se houver. Sem lista de imagens, o roteiro sai só com avatar.

Se o material estiver incompleto, **não invente regras, prazos, valores ou nomes**. Escreva só o que o material sustenta e omita o que não souber, sem comentar a omissão.

### 2. Estrutura (interna; só aparece no texto pelas transições e pelas marcações)
1. **Abertura (avatar):** cumprimento curto, o tema e por que importa (2 a 3 frases).
2. **Desenvolvimento:** de 3 a 5 ideias ou passos, na ordem em que o colaborador vai aplicá-los. Cada um com uma explicação curta e, quando ajudar, um exemplo do dia a dia do hotel. Com imagens disponíveis, distribua entre cenas de imagem e `[AVATAR]` conforme a seção de cenas.
3. **Fechamento (avatar):** resumo em uma ou duas frases e uma orientação final (a quem recorrer em caso de dúvida, se o material disser).

A estrutura aparece na fala só pelas transições ("Vamos começar por…", "Agora, o segundo ponto…"), nunca como título ou número.

### 3. Redação
- Tom acolhedor e profissional, tratando o colaborador por "você". (Ajuste se o usuário pedir outro tom.)
- Texto fiel ao material-fonte. Simplifique a linguagem, mas não mude o sentido.
- Evite jargão interno sem explicação.

### 4. Conferência antes de entregar (silenciosa: corrija o que precisar e não relate o resultado)
- **Conte os caracteres falados** (texto sem as linhas de marcação) com uma ferramenta, em vez de estimar. Deve ficar abaixo de 5.000.
- Confira cada marcação: está **sozinha na linha**, escrita exatamente como `[IMAGEM: arquivo.ext]` ou `[AVATAR]`, o arquivo está na lista do usuário e a cena tem texto depois dela.
- Confira se o avatar abre e fecha o vídeo, e se não há mais de 2 cenas de imagem seguidas.
- Releia procurando listas, numeração no início de linha, markdown, parênteses, siglas e números que a voz leria mal.
- Confira se tudo o que está no roteiro vem do material-fonte.

## Quando o material é grande demais
Se o conteúdo não cabe em ~3.500 caracteres falados sem perder o essencial, **divida em partes**, cada uma um roteiro independente de um único assunto, com abertura e fechamento próprios e curtos. Nomeie como "Tema – Parte 1 de 3". Gere cada parte como um `.txt` separado, sem comentar a divisão.

## Entrega: sempre um .zip de .txt, sem explicações

Gere direto, sem descrever o que foi feito.

1. Crie um arquivo `.txt` (UTF-8) por roteiro, com **somente o texto do roteiro e, quando houver imagens, as marcações `[IMAGEM: ...]` e `[AVATAR]`**: sem título, cabeçalho, contagem de caracteres, observações ou comentários dentro do arquivo.
2. Nomeie cada arquivo de forma clara e sem caracteres especiais, no padrão `Setor - Titulo.txt` (por exemplo `Recepcao - Check-in de hospedes.txt`). O nome tende a virar o título no portal.
3. Compile todos os `.txt` em um único `.zip` (por exemplo `roteiros-carmel-AAAA-MM-DD.zip`), usando Python (`zipfile`) ou o comando `zip`. Mesmo que seja um só roteiro, entregue em `.zip`.
4. Envie o `.zip` com SendUserFile.
5. A resposta final tem **no máximo uma linha** (por exemplo: "Roteiros prontos no zip."). Não liste os roteiros, não resuma o conteúdo, não informe contagem de caracteres, duração, divisão em partes nem pontos a confirmar.

Lembrete só para o usuário, se ele perguntar: os `.txt` precisam ser colocados na pasta `<Setor>/Roteiros` do Drive, e as imagens citadas na pasta `<Setor>/Imagens`, para entrar no portal.

## Exemplo sem imagens (ilustrativo; o conteúdo é inventado só para mostrar o estilo)

Bem-vindo ao treinamento de recepção. Hoje vamos falar sobre como fazer um check-in acolhedor e sem filas. Um bom primeiro contato define a experiência inteira do hóspede.

Vamos começar pelo cumprimento. Levante o olhar, sorria e cumprimente o hóspede assim que ele se aproximar do balcão, mesmo que você ainda esteja finalizando outro atendimento.

Em seguida, confirme o nome da reserva e peça um documento com foto. Faça isso de forma tranquila, explicando o motivo, para que o hóspede se sinta seguro.

Por fim, apresente os horários do café da manhã e os serviços do hotel, e deseje uma ótima estadia. Em resumo: cumprimentar, confirmar, orientar e se despedir com simpatia. Em caso de dúvida, procure o seu gestor.

## O que não fazer
- Não reescrever ou "melhorar" um roteiro que o usuário trouxe pronto, a menos que ele peça. O portal narra o texto literalmente. Se ele trouxe um roteiro pronto e pede para intercalar, **só acrescente as marcações**, sem mudar as palavras.
- Não passar de 5.000 caracteres falados.
- Não incluir listas, títulos ou instruções de cena em texto comum. As únicas marcações permitidas são `[IMAGEM: ...]` e `[AVATAR]`.
- Não inventar nomes de imagem, nem usar marcação quando o usuário não informou imagens.
- Não citar objetos no texto de animação (`animar: ...`).
- Não descrever, resumir nem comentar o que foi gerado: a resposta é apenas a entrega do `.zip`.
- Não inventar informações sobre políticas, valores, prazos ou contatos do hotel.
