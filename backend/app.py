import os
import re
import json
from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

basedir = os.path.abspath(os.path.dirname(__file__))
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", f"sqlite:///{os.path.join(basedir, 'tutorhistoria.db')}"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

from models import db, Aluno, NoDominio, Questao, ProgressoAluno, HistoricoResposta, calcular_nivel

db.init_app(app)

with app.app_context():
    db.create_all()
    from seed import seed_database
    seed_database()


# ---------------------------------------------------------------------------
# Helper: get or create ProgressoAluno for a given student and node
# ---------------------------------------------------------------------------

def _get_or_create_progresso(aluno_id: int, no_id: int) -> ProgressoAluno:
    progresso = ProgressoAluno.query.filter_by(aluno_id=aluno_id, no_id=no_id).first()
    if progresso is None:
        progresso = ProgressoAluno(aluno_id=aluno_id, no_id=no_id, dominio=0, tentativas=0, acertos=0, erros_consecutivos=0)
        db.session.add(progresso)
        db.session.flush()
    return progresso


# ---------------------------------------------------------------------------
# Helper: determine which nodes are unlocked / dominated for a student
# ---------------------------------------------------------------------------

def _calcular_status_nos(aluno_id: int):
    nos = NoDominio.query.order_by(NoDominio.camada).all()
    progressos_map = {
        p.no_id: p
        for p in ProgressoAluno.query.filter_by(aluno_id=aluno_id).all()
    }

    desbloqueados = []
    dominados = []

    for no in nos:
        prereqs = no.prerequisitos  # list of no_id ints
        if not prereqs:
            desbloqueados.append(no.id)
        else:
            todos_dominados = all(
                progressos_map.get(pr_id) is not None and progressos_map[pr_id].dominio >= 70
                for pr_id in prereqs
            )
            if todos_dominados:
                desbloqueados.append(no.id)

        progresso = progressos_map.get(no.id)
        if progresso and progresso.dominio >= 70:
            dominados.append(no.id)

    return desbloqueados, dominados


# ---------------------------------------------------------------------------
# ROUTES
# ---------------------------------------------------------------------------

@app.route("/api/aluno/<nome>", methods=["GET"])
def get_or_create_aluno(nome: str):
    """Find or create a student by name. Returns {id, nome, xp, nivel}."""
    if not nome or not nome.strip():
        return jsonify({"erro": "Nome inválido"}), 400

    nome = nome.strip()
    aluno = Aluno.query.filter_by(nome=nome).first()
    if aluno is None:
        aluno = Aluno(nome=nome, xp=0)
        db.session.add(aluno)
        db.session.commit()

    return jsonify(aluno.to_dict()), 200


@app.route("/api/dominio", methods=["GET"])
def get_dominio():
    """Return full knowledge graph with nodes, questions, and prerequisites."""
    nos = NoDominio.query.order_by(NoDominio.camada, NoDominio.id).all()
    resultado = []
    for no in nos:
        no_dict = no.to_dict()
        questoes = Questao.query.filter_by(no_id=no.id).all()
        no_dict["questoes"] = [q.to_dict() for q in questoes]
        resultado.append(no_dict)

    return jsonify({"nos": resultado}), 200


@app.route("/api/aluno/<int:aluno_id>/progresso", methods=["GET"])
def get_progresso(aluno_id: int):
    """Return all node progress for a student including unlocked/dominated status."""
    aluno = Aluno.query.get(aluno_id)
    if aluno is None:
        return jsonify({"erro": "Aluno não encontrado"}), 404

    nos = NoDominio.query.order_by(NoDominio.camada, NoDominio.id).all()
    desbloqueados, dominados = _calcular_status_nos(aluno_id)

    progressos_map = {
        p.no_id: p
        for p in ProgressoAluno.query.filter_by(aluno_id=aluno_id).all()
    }

    # Pontos de interesse: seções onde o aluno errou pelo menos uma questão
    erros_por_no = {}
    rows = (
        db.session.query(Questao.no_id, Questao.paragrafo_ref)
        .join(HistoricoResposta, Questao.id == HistoricoResposta.questao_id)
        .filter(
            HistoricoResposta.aluno_id == aluno_id,
            HistoricoResposta.correta == False,  # noqa: E712
            Questao.paragrafo_ref.isnot(None),
        )
        .distinct()
        .all()
    )
    for no_id_row, ref in rows:
        erros_por_no.setdefault(no_id_row, []).append(ref)

    resultado = []
    for no in nos:
        progresso = progressos_map.get(no.id)
        resultado.append({
            "no_id": no.id,
            "titulo": no.titulo,
            "camada": no.camada,
            "prerequisitos": no.prerequisitos,
            "dominio": progresso.dominio if progresso else 0,
            "tentativas": progresso.tentativas if progresso else 0,
            "acertos": progresso.acertos if progresso else 0,
            "erros_consecutivos": progresso.erros_consecutivos if progresso else 0,
            "desbloqueado": no.id in desbloqueados,
            "dominado": no.id in dominados,
            "pontos_interesse": erros_por_no.get(no.id, []),
        })

    return jsonify({
        "aluno_id": aluno_id,
        "xp": aluno.xp,
        "nivel": calcular_nivel(aluno.xp),
        "nos": resultado,
    }), 200


@app.route("/api/resposta", methods=["POST"])
def registrar_resposta():
    """
    Register a student answer.

    Body JSON:
        aluno_id               (int)
        no_id                  (int)
        questao_id             (int)
        tipo                   ('multipla_escolha' | 'aberta')
        correta                (bool)
        palavras_chave_encontradas  (int, for open questions)

    Returns:
        novo_dominio, xp_atual, nivel, desbloqueados, dominados,
        erros_consecutivos, dica_sugerida
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"erro": "Corpo da requisição inválido ou ausente"}), 400

    required = ["aluno_id", "no_id", "questao_id", "tipo", "correta"]
    for campo in required:
        if campo not in data:
            return jsonify({"erro": f"Campo obrigatório ausente: {campo}"}), 400

    aluno_id = data["aluno_id"]
    no_id = data["no_id"]
    questao_id = data["questao_id"]
    tipo = data["tipo"]
    correta = bool(data["correta"])
    raw_pk = data.get("palavras_chave_encontradas", 0)
    palavras_chave_encontradas = len(raw_pk) if isinstance(raw_pk, list) else int(raw_pk)

    aluno = Aluno.query.get(aluno_id)
    if aluno is None:
        return jsonify({"erro": "Aluno não encontrado"}), 404

    no = NoDominio.query.get(no_id)
    if no is None:
        return jsonify({"erro": "Nó de domínio não encontrado"}), 404

    questao = Questao.query.get(questao_id)
    if questao is None:
        return jsonify({"erro": "Questão não encontrada"}), 404

    # --- Dominio delta ---
    progresso = _get_or_create_progresso(aluno_id, no_id)
    progresso.tentativas += 1

    if tipo == "multipla_escolha":
        if correta:
            delta_dominio = 20
            xp_ganho = 10
            progresso.acertos += 1
            progresso.erros_consecutivos = 0
        else:
            delta_dominio = -10
            xp_ganho = 0
            progresso.erros_consecutivos += 1
    elif tipo == "aberta":
        if correta:
            delta_dominio = 15
            xp_ganho = 20
            progresso.acertos += 1
            progresso.erros_consecutivos = 0
        else:
            delta_dominio = 0
            xp_ganho = 0
            progresso.erros_consecutivos += 1
    else:
        return jsonify({"erro": f"Tipo de questão desconhecido: {tipo}"}), 400

    novo_dominio = max(0, min(100, progresso.dominio + delta_dominio))
    progresso.dominio = novo_dominio

    # --- XP ---
    aluno.xp += xp_ganho

    # --- Historico ---
    historico = HistoricoResposta(
        aluno_id=aluno_id,
        questao_id=questao_id,
        correta=correta,
    )
    db.session.add(historico)
    db.session.commit()

    # --- Status dos nós ---
    desbloqueados, dominados = _calcular_status_nos(aluno_id)

    # --- Dica quando erros consecutivos >= 2 ---
    dica_sugerida = None
    if progresso.erros_consecutivos >= 2:
        dica_sugerida = (
            "Você errou várias vezes seguidas. Recomendamos reler o conteúdo do nó "
            f'"{no.titulo}" antes de continuar.'
        )

    return jsonify({
        "novo_dominio": novo_dominio,
        "xp_ganho": xp_ganho,
        "xp_atual": aluno.xp,
        "nivel": calcular_nivel(aluno.xp),
        "desbloqueados": desbloqueados,
        "dominados": dominados,
        "erros_consecutivos": progresso.erros_consecutivos,
        "dica_sugerida": dica_sugerida,
        "feedback_erro": questao.feedback_erro if not correta else None,
    }), 200


@app.route("/api/aluno/<int:aluno_id>/stats", methods=["GET"])
def get_stats(aluno_id: int):
    """Return aggregate statistics for a student."""
    aluno = Aluno.query.get(aluno_id)
    if aluno is None:
        return jsonify({"erro": "Aluno não encontrado"}), 404

    total_respostas = HistoricoResposta.query.filter_by(aluno_id=aluno_id).count()
    acertos = HistoricoResposta.query.filter_by(aluno_id=aluno_id, correta=True).count()
    erros = total_respostas - acertos

    nos_dominados = ProgressoAluno.query.filter(
        ProgressoAluno.aluno_id == aluno_id,
        ProgressoAluno.dominio >= 70,
    ).count()

    return jsonify({
        "aluno_id": aluno_id,
        "nome": aluno.nome,
        "xp": aluno.xp,
        "nivel": calcular_nivel(aluno.xp),
        "total_respostas": total_respostas,
        "acertos": acertos,
        "erros": erros,
        "nos_dominados": nos_dominados,
        "taxa_acerto": round((acertos / total_respostas * 100), 1) if total_respostas > 0 else 0,
    }), 200


# ---------------------------------------------------------------------------
# Tutor IA — Groq streaming
# ---------------------------------------------------------------------------

def _strip_html(html: str) -> str:
    text = re.sub(r'<[^>]+>', ' ', html or '')
    return re.sub(r'\s+', ' ', text).strip()

def _extrair_secoes(html: str) -> list[dict]:
    """Extrai seções do HTML por bloco <section>, capturando id e ignorando fontes."""
    secoes = []
    for match in re.finditer(r'<section([^>]*)>(.*?)</section>', html, re.DOTALL):
        attrs, bloco = match.group(1), match.group(2)
        id_match = re.search(r'id=["\']([^"\']+)["\']', attrs)
        section_id = id_match.group(1) if id_match else None
        h = re.search(r'<h[234][^>]*>(.*?)</h[234]>', bloco)
        titulo = re.sub(r'<[^>]+>', '', h.group(1)).strip() if h else ''
        if not titulo or 'Fontes' in titulo or 'Conclus' in titulo:
            continue
        texto = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', bloco)).strip()
        secoes.append({'id': section_id, 'titulo': titulo, 'texto': texto})
    return secoes

@app.route("/api/tutor/chat", methods=["POST"])
def tutor_chat():
    data = request.get_json()
    messages        = data.get("messages", [])
    aluno_nome      = data.get("aluno_nome", "Aluno")
    no_id           = int(data.get("no_id", 1))
    pontos_interesse = data.get("pontos_interesse", [])

    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        return jsonify({"erro": "GROQ_API_KEY não configurada no servidor"}), 503

    no = NoDominio.query.get(no_id)
    if not no:
        return jsonify({"erro": "Nó não encontrado"}), 404

    secoes = _extrair_secoes(no.conteudo)
    partes_texto = "\n\n".join(
        f"PARTE {i+1} — {s['titulo']}:\n{s['texto']}"
        for i, s in enumerate(secoes)
    )

    # Seções onde o aluno errou questões
    secoes_com_erro = [s for s in secoes if s.get('id') in pontos_interesse]
    nomes_erros = [s['titulo'] for s in secoes_com_erro]

    if secoes_com_erro:
        erros_texto = "\n\n".join(
            f"SEÇÃO COM ERRO — {s['titulo']}:\n{s['texto']}"
            for s in secoes_com_erro
        )
        fluxo = f"""CONTEXTO: {aluno_nome} já tentou o quiz deste nó e errou questões sobre as seguintes seções: {', '.join(f'"{t}"' for t in nomes_erros)}.

FLUXO OBRIGATÓRIO (MODO REVISÃO):
1. PRIMEIRA mensagem: cumprimente {aluno_nome} pelo nome, diga que percebeu que ele teve dificuldade em: {', '.join(f'"{t}"' for t in nomes_erros)}. Pergunte se quer esclarecer alguma dúvida sobre essas partes antes de tentar o quiz novamente. NÃO explique o conteúdo ainda.
2. Se o aluno confirmar dúvida ou pedir explicação: explique a seção com erro de forma clara e detalhada.
3. Após explicar, pergunte se ficou claro ou se tem mais dúvidas.
4. Quando o aluno não tiver mais dúvidas, encoraje-o a tentar o quiz novamente.

SEÇÕES PRIORITÁRIAS (onde o aluno errou):
{erros_texto}

CONTEÚDO COMPLETO DISPONÍVEL (para contexto):
{partes_texto}"""
    else:
        fluxo = f"""OBJETIVO: Ensinar o conteúdo em {len(secoes)} partes (~20% por vez), de forma conversacional.

FLUXO OBRIGATÓRIO:
1. PRIMEIRA mensagem: cumprimente {aluno_nome} pelo nome, diga brevemente o que vão estudar juntos e PERGUNTE se ele está pronto para começar. NÃO explique conteúdo nesta mensagem.
2. Quando o aluno disser que está pronto (sim, pode começar, pronto, ok, etc.): explique apenas a PARTE 1.
3. Após a PARTE 1, pergunte se ele entendeu ou tem dúvidas.
4. Se confirmar entendimento, avance para a próxima parte. Se tiver dúvida, responda e confirme antes de avançar.
5. Continue até a PARTE {len(secoes)}, depois parabenize e diga explicitamente que ele deve clicar no botão "Iniciar Questões" que aparece na tela para testar o conhecimento. NUNCA faça perguntas de quiz você mesmo — isso é responsabilidade do sistema.

CONTEÚDO PARA ENSINAR:
{partes_texto}"""

    descricao_imagem = {
        1: "um mapa das alianças europeias de 1914 exibido no lado direito da tela — referencie-o quando pertinente (ex: 'observe no mapa que...')",
        2: "uma fotografia histórica de Sarajevo relacionada ao assassinato do Arquiduque Franz Ferdinand em 28 de junho de 1914, exibida no lado direito da tela — referencie-a quando pertinente",
        3: "um mapa e fotografia das trincheiras do front ocidental exibidos no lado direito da tela — referencie-os quando pertinente (ex: 'veja como as trincheiras se estendiam...')",
        4: "uma imagem com tecnologias da Primeira Guerra (tanque, aviões, máscaras de gás) exibida no lado direito da tela — referencie-a quando pertinente",
        5: "uma fotografia da celebração do Armistício de 11 de novembro de 1918 exibida no lado direito da tela — referencie-a quando pertinente",
        6: "uma fotografia da assinatura do Tratado de Versalhes no Salão dos Espelhos em 1919, exibida no lado direito da tela — referencie-a quando pertinente",
    }.get(no_id, "uma imagem histórica relacionada ao tema exibida no lado direito da tela")

    system_prompt = f"""Você é o Prof. Otto, tutor do TutorHistória, especialista na Primeira Guerra Mundial.

O aluno se chama {aluno_nome} e está estudando "{no.titulo}".
Há {descricao_imagem}.

{fluxo}

RESTRIÇÕES:
- NUNCA explique mais de uma parte por mensagem — um foco por vez
- Conclua sempre o raciocínio que começou, nunca corte a resposta no meio
- Tom amigável e encorajador, mas direto e objetivo
- SEMPRE em português do Brasil
"""

    def generate():
        try:
            from groq import Groq
            client = Groq(api_key=api_key)
            stream = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "system", "content": system_prompt}] + messages,
                stream=True,
                temperature=0.7,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield f"data: {json.dumps({'text': delta})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(e):
    return jsonify({"erro": "Rota não encontrada"}), 404


@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({"erro": "Método não permitido"}), 405


@app.errorhandler(500)
def internal_error(e):
    db.session.rollback()
    return jsonify({"erro": "Erro interno do servidor"}), 500


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
