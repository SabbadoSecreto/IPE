# TutorHistória — Relatório do Projeto

**Disciplina:** Inteligência Artificial para Educação  
**Projeto:** Sistema Tutor Inteligente (ITS) — Primeira Guerra Mundial  

---

## O que é o projeto

O TutorHistória é um Sistema Tutor Inteligente (ITS) para ensinar o conteúdo da Primeira Guerra Mundial. Em vez de o aluno ler um texto estático e responder questões, o sistema adapta o ensino com base no desempenho de cada um — desbloqueando conteúdos progressivamente, identificando onde o aluno errou e acionando um tutor com IA para explicar o conteúdo de forma conversacional.

---

## Objetivos

- Aplicar os conceitos de ITS vistos em aula em um sistema funcional e completo
- Implementar um modelo do aluno real, com rastreamento de domínio por tópico
- Demonstrar como a IA generativa pode atuar como tutor adaptativo dentro de um ITS
- Criar uma experiência de aprendizado que vai além do "lê e responde"

---

## Arquitetura do ITS

Um ITS clássico tem quatro componentes. Implementamos todos:

| Componente | O que faz | Como implementamos |
|---|---|---|
| **Modelo do Domínio** | Representa o conhecimento a ser ensinado | Grafo de conhecimento com 6 nós organizados em camadas, cada um com pré-requisitos |
| **Modelo do Aluno** | Rastreia o que o aluno sabe | Variável de domínio (0–100%) por nó, atualizada a cada resposta |
| **Modelo Pedagógico** | Decide como ensinar | Desbloqueio por domínio ≥ 70%, feedback imediato, tutor IA por partes |
| **Interface** | Como o aluno interage | Frontend React com tema visual da época (sépia, cáqui, dourado) |

---

## Conceitos de IA para Educação aplicados

### Grafo de Conhecimento com Pré-requisitos
O conteúdo foi organizado em 6 nós em camadas. Um nó só é desbloqueado quando o aluno atinge 70% de domínio nos pré-requisitos. Isso garante que o aluno não pule etapas sem ter a base necessária.

### Mastery Learning
Baseado em Benjamin Bloom: o aluno só avança quando demonstra domínio suficiente no tópico atual. O limiar de 70% foi escolhido como equilíbrio entre exigência e progressão.

### Modelo do Aluno Adaptativo
Cada resposta atualiza o domínio do aluno:
- Múltipla escolha correta: +20 pontos
- Múltipla escolha errada: -10 pontos
- Dissertativa correta: +15 pontos

O sistema também rastreia erros consecutivos e sugere revisão do conteúdo quando necessário.

### Pontos de Interesse (Metacognição)
Quando o aluno erra uma questão, o parágrafo do texto que gerou aquela questão é marcado com um indicador visual na próxima leitura. Isso faz o aluno tomar consciência de onde está a lacuna no conhecimento — um suporte à metacognição.

### Tutor Conversacional com IA Generativa
Nos nós com tutor IA (Prof. Otto), o conteúdo é ensinado em partes, uma de cada vez. O tutor:
1. Pergunta se o aluno está pronto antes de começar
2. Explica ~20% do conteúdo por mensagem
3. Pergunta se entendeu antes de avançar
4. Responde dúvidas antes de continuar
5. Ao terminar, instrui o aluno a fazer o quiz

Isso implementa **scaffolding progressivo** e a ideia de **Zona de Desenvolvimento Proximal** (Vygotsky) — o tutor opera no limite do que o aluno ainda não sabe, mas consegue aprender com suporte.

### Gamificação
- **XP** acumulado a cada resposta certa
- **Patentes militares** que sobem conforme o XP (Recruta → Cabo → Sargento → Tenente → Capitão → Major → General)

A gamificação aumenta o engajamento e dá ao aluno um senso de progressão além do domínio técnico.

### Feedback Imediato e Personalizado
Cada questão errada retorna o `feedback_erro` específico daquela questão, explicando o erro. Questões dissertativas verificam palavras-chave com normalização de acentos e capitalização para não penalizar o aluno por detalhes de formatação.

---

## Decisões técnicas

**Por que Flask + React?**  
Flask é leve e direto para APIs REST. React permite uma interface reativa sem recarregar a página a cada interação — importante para a experiência de quiz e tutor em tempo real.

**Por que Groq + Llama 3.1?**  
A Groq oferece inferência gratuita com latência muito baixa. O Llama 3.1-8b-instant é suficientemente capaz para seguir instruções pedagógicas estruturadas e responder em português, sem custo.

**Por que SSE (Server-Sent Events) para o tutor?**  
Permite que o texto do tutor apareça palavra por palavra, como uma conversa real — muito mais natural do que esperar a resposta inteira antes de exibir.

**Por que SQLite?**  
O projeto não exige persistência longa. O banco dura enquanto o servidor está rodando, o que é suficiente para uma sessão de estudo.

---

## Estrutura do sistema

```
backend/
  app.py        # API Flask: aluno, domínio, resposta, tutor IA
  models.py     # Modelos: Aluno, NoDominio, Questao, ProgressoAluno
  seed.py       # Conteúdo completo da 1ª Guerra com 36 questões
  
frontend/
  src/
    pages/
      TelaLogin.jsx      # Entrada do aluno pelo nome
      MapaDominio.jsx    # Grafo visual dos 6 nós com status
      TelaEstudo.jsx     # Leitura/tutor IA por nó
      TelaQuiz.jsx       # Quiz adaptativo
    components/
      TutorChat.jsx      # Chat com Prof. Otto via SSE
    context/
      AlunoContext.jsx   # Estado global do aluno
```

---

## O que o sistema faz na prática

1. Aluno entra com seu nome → sistema cria ou recupera o perfil
2. Vê o mapa de domínio com os nós bloqueados/desbloqueados
3. Entra em um nó disponível → estuda com o tutor IA (nós 1–6) ou lê o texto
4. Faz o quiz → domínio é atualizado em tempo real
5. Ao atingir 70%, o próximo nó desbloqueia
6. Se errou questões, os trechos relevantes ficam marcados na próxima visita

---

## Conclusão

O projeto demonstra que é possível construir um ITS completo e funcional com ferramentas modernas e acessíveis. A combinação de grafo de conhecimento, modelo do aluno adaptativo e tutor com IA generativa cobre os principais pilares teóricos da área, entregando uma experiência de aprendizado significativamente mais rica do que um formulário de questões estático.
