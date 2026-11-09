
from flask import Flask, jsonify, render_template, session, redirect, url_for
from flask import request
from werkzeug.security import generate_password_hash, check_password_hash
import mysql.connector
from dotenv import load_dotenv
import os

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")

if not app.secret_key:
    raise RuntimeError("SECRET_KEY não configurada no ambiente.")


def validar_cpf(cpf):
    if len(cpf) != 11 or not cpf.isascii() or not cpf.isdigit():
        return False

    if cpf == cpf[0] * 11:
        return False

    for tamanho in (9, 10):
        soma = sum(
            int(cpf[i]) * (tamanho + 1 - i)
            for i in range(tamanho)
        )

        digito = (soma * 10) % 11

        if digito == 10:
            digito = 0

        if digito != int(cpf[tamanho]):
            return False

    return True
@app.context_processor
def contador_carrinho():
    carrinho = session.get("carrinho", {})
    quantidade_total = sum(int(qtd) for qtd in carrinho.values())
    return {"quantidade_carrinho": quantidade_total}

@app.route("/")
def inicio():
    try:
        conexao = mysql.connector.connect(
            host=os.getenv("DB_HOST", "localhost"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME", "cafeteria_shop_cr")
        )

        cursor = conexao.cursor(dictionary=True)
        cursor.execute("""
            SELECT id_produto, nome, descricao, preco
            FROM produto
            WHERE status = 'ativo'
            ORDER BY id_produto
        """)

        produtos = cursor.fetchall()

        cursor.close()
        conexao.close()

        return render_template("index.html", produtos=produtos)

    except mysql.connector.Error:
        app.logger.exception("Erro ao carregar produtos")
        return "Erro ao carregar o cardápio.", 500

@app.route("/categorias")
def categorias():
    try:
        conexao = mysql.connector.connect(
            host=os.getenv("DB_HOST", "localhost"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME", "cafeteria_shop_cr")
        )

        cursor = conexao.cursor(dictionary=True)
        cursor.execute("SELECT * FROM categoria")
        resultado = cursor.fetchall()

        cursor.close()
        conexao.close()

        return jsonify(resultado)

    except mysql.connector.Error:
        app.logger.exception("Erro ao consultar o banco")
        return jsonify({"erro": "Falha ao consultar categorias"}), 500

@app.route("/adicionar-carrinho/<int:id_produto>", methods=["POST"])
def adicionar_carrinho(id_produto):
    try:
        conexao = mysql.connector.connect(
            host=os.getenv("DB_HOST", "localhost"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME", "cafeteria_shop_cr")
        )

        cursor = conexao.cursor(dictionary=True)
        cursor.execute(
            "SELECT id_produto FROM produto WHERE id_produto = %s AND status = 'ativo'",
            (id_produto,)
        )
        produto = cursor.fetchone()

        cursor.close()
        conexao.close()

        if produto is None:
            return "Produto não encontrado.", 404

        carrinho = session.get("carrinho", {})
        chave = str(id_produto)

        carrinho[chave] = carrinho.get(chave, 0) + 1

        session["carrinho"] = carrinho

        return redirect(url_for("inicio"))

    except mysql.connector.Error:
        app.logger.exception("Erro ao adicionar produto")
        return "Erro ao adicionar produto ao carrinho.", 500

@app.route("/carrinho")
def ver_carrinho():
    carrinho = session.get("carrinho", {})
    produtos_carrinho = []
    total = 0

    if carrinho:
        try:
            conexao = mysql.connector.connect(
                host=os.getenv("DB_HOST", "localhost"),
                user=os.getenv("DB_USER"),
                password=os.getenv("DB_PASSWORD"),
                database=os.getenv("DB_NAME", "cafeteria_shop_cr")
            )

            cursor = conexao.cursor(dictionary=True)

            for id_produto, quantidade in carrinho.items():
                cursor.execute(
                    "SELECT id_produto, nome, preco FROM produto WHERE id_produto = %s",
                    (int(id_produto),)
                )

                produto = cursor.fetchone()

                if produto:
                    produto["quantidade"] = quantidade
                    produto["subtotal"] = produto["preco"] * quantidade
                    total += produto["subtotal"]
                    produtos_carrinho.append(produto)

            cursor.close()
            conexao.close()

        except mysql.connector.Error:
            app.logger.exception("Erro ao consultar carrinho")
            return "Erro ao carregar o carrinho.", 500

    return render_template(
        "carrinho.html",
        produtos=produtos_carrinho,
        total=total
    )
@app.route("/remover-carrinho/<int:id_produto>", methods=["POST"])
def remover_carrinho(id_produto):
    carrinho = session.get("carrinho", {})
    chave = str(id_produto)

    if chave in carrinho:
        del carrinho[chave]
        session["carrinho"] = carrinho

    return redirect(url_for("ver_carrinho"))
@app.route("/alterar-quantidade/<int:id_produto>/<acao>", methods=["POST"])
def alterar_quantidade(id_produto, acao):
    carrinho = session.get("carrinho", {})
    chave = str(id_produto)

    if chave in carrinho:
        quantidade = int(carrinho[chave])

        if acao == "aumentar":
            quantidade += 1
        elif acao == "diminuir":
            quantidade -= 1
        else:
            return "Ação inválida.", 400

        if quantidade <= 0:
            del carrinho[chave]
        else:
            carrinho[chave] = quantidade

        session["carrinho"] = carrinho

    return redirect(url_for("ver_carrinho"))


@app.route("/finalizar", methods=["GET", "POST"])
def finalizar_pedido():
    carrinho = session.get("carrinho", {})

    if not carrinho:
        return redirect(url_for("ver_carrinho"))

    cliente_id_logado = session.get("cliente_id")

    if request.method == "GET":
        return render_template("finalizar.html")

    forma_pagamento = request.form.get(
        "forma_pagamento", ""
    ).strip()

    if forma_pagamento not in ("pix", "cartao"):
        return "Selecione uma forma de pagamento válida.", 400

    conexao = None
    cursor = None

    try:
        conexao = mysql.connector.connect(
            host=os.getenv("DB_HOST", "localhost"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME", "cafeteria_shop_cr")
        )

        cursor = conexao.cursor(dictionary=True)

        if cliente_id_logado:
            # Cliente logado: reutilizar o cadastro.
            cursor.execute(
                """
                SELECT id_cliente
                FROM cliente
                WHERE id_cliente = %s
                """,
                (cliente_id_logado,)
            )

            cliente = cursor.fetchone()

            if not cliente:
                return (
                    "Cliente não encontrado. Faça login novamente.",
                    401
                )

            id_cliente = cliente["id_cliente"]

        else:
            # Cliente novo: validar e cadastrar.
            nome = request.form.get("nome", "").strip()
            cpf = "".join(
                c for c in request.form.get("cpf", "")
                if c.isascii() and c.isdigit()
            )
            email = request.form.get(
                "email", ""
            ).strip().lower()
            telefone = request.form.get(
                "telefone", ""
            ).strip()
            senha = request.form.get("senha", "")
            confirmar_senha = request.form.get(
                "confirmar_senha", ""
            )

            if not nome or not email or not telefone:
                return (
                    "Preencha todos os campos obrigatórios.",
                    400
                )

            if not validar_cpf(cpf):
                return (
                    "CPF inválido. Confira os números informados.",
                    400
                )

            if len(senha) < 8:
                return (
                    "A senha deve ter pelo menos 8 caracteres.",
                    400
                )

            if senha != confirmar_senha:
                return "As senhas não coincidem.", 400

            cursor.execute(
                """
                SELECT id_cliente
                FROM cliente
                WHERE cpf = %s OR email = %s
                LIMIT 1
                """,
                (cpf, email)
            )

            if cursor.fetchone():
                return (
                    "CPF ou e-mail já cadastrado. "
                    "Faça login para continuar.",
                    409
                )

            senha_hash = generate_password_hash(senha)

            cursor.execute(
                """
                INSERT INTO cliente
                    (nome, cpf, email, telefone, senha_hash)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (nome, cpf, email, telefone, senha_hash)
            )

            id_cliente = cursor.lastrowid

        # Conferir todos os produtos do carrinho.
        itens_pedido = []
        valor_total = 0

        for id_produto, quantidade in carrinho.items():
            quantidade = int(quantidade)

            if quantidade <= 0:
                raise ValueError("Quantidade inválida.")

            cursor.execute(
                """
                SELECT id_produto, preco
                FROM produto
                WHERE id_produto = %s
                  AND status = 'ativo'
                """,
                (int(id_produto),)
            )

            produto = cursor.fetchone()

            if not produto:
                raise ValueError("Produto indisponível.")

            preco = produto["preco"]
            valor_total += preco * quantidade

            itens_pedido.append(
                (int(id_produto), quantidade, preco)
            )

        if not itens_pedido:
            raise ValueError("Carrinho vazio.")

        # Registrar pedido.
        cursor.execute(
            """
            INSERT INTO pedido
                (status, valor_total, id_cliente)
            VALUES (%s, %s, %s)
            """,
            (
                "aguardando_pagamento",
                valor_total,
                id_cliente
            )
        )

        id_pedido = cursor.lastrowid

        # Registrar todos os itens do pedido.
        for id_produto, quantidade, preco in itens_pedido:
            cursor.execute(
                """
                INSERT INTO item_pedido
                    (quantidade, preco_unitario,
                     id_pedido, id_produto)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    quantidade,
                    preco,
                    id_pedido,
                    id_produto
                )
            )

        # Registrar pagamento simulado.
        cursor.execute(
            """
            INSERT INTO pagamento
                (forma_pagamento, status_pagamento,
                 valor_pago, id_pedido)
            VALUES (%s, %s, %s, %s)
            """,
            (
                forma_pagamento,
                "pendente",
                valor_total,
                id_pedido
            )
        )

        # Confirmar alterações no MySQL.
        conexao.commit()

        # Manter cliente conectado após a compra.
        session["cliente_id"] = id_cliente

        if not cliente_id_logado:
            session["cliente_nome"] = nome

        # Limpar carrinho somente após salvar.
        session.pop("carrinho", None)

        return render_template(
            "pedido_sucesso.html",
            id_pedido=id_pedido
        )

    except ValueError as erro:
        if conexao is not None:
            conexao.rollback()

        app.logger.warning(
            "Pedido inválido: %s", erro
        )

        return (
            "Não foi possível finalizar o pedido. "
            "Verifique os produtos do carrinho.",
            400
        )

    except mysql.connector.IntegrityError:
        if conexao is not None:
            conexao.rollback()

        app.logger.warning(
            "Erro de integridade ao finalizar pedido"
        )

        return (
            "Não foi possível concluir o cadastro "
            "ou o pedido. Verifique os dados.",
            409
        )

    except mysql.connector.Error:
        if conexao is not None:
            conexao.rollback()

        app.logger.exception(
            "Erro ao finalizar pedido"
        )

        return (
            "Não foi possível finalizar o pedido.",
            500
        )

    finally:
        if cursor is not None:
            cursor.close()

        if conexao is not None and conexao.is_connected():
            conexao.close()
@app.route("/login-admin", methods=["GET", "POST"])
def login_admin():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "")

        try:
            conexao = mysql.connector.connect(
                host=os.getenv("DB_HOST", "localhost"),
                user=os.getenv("DB_USER"),
                password=os.getenv("DB_PASSWORD"),
                database=os.getenv("DB_NAME", "cafeteria_shop_cr")
            )

            cursor = conexao.cursor(dictionary=True)

            cursor.execute(
                """
                SELECT id_administrador, nome, senha_hash
                FROM administrador
                WHERE email = %s
                LIMIT 1
                """,
                (email,)
            )

            admin = cursor.fetchone()

            cursor.close()
            conexao.close()

            if not admin or not check_password_hash(
                admin["senha_hash"], senha
            ):
                return "E-mail ou senha incorretos.", 401

            session.clear()
            session["admin_id"] = admin["id_administrador"]
            session["admin_nome"] = admin["nome"]

            return redirect(url_for("painel_admin"))

        except mysql.connector.Error:
            app.logger.exception("Erro no login administrativo")
            return "Erro ao realizar login.", 500

    return render_template("login_admin.html")


@app.route("/painel-admin")
def painel_admin():
    if not session.get("admin_id"):
        return redirect(url_for("login_admin"))

    try:
        conexao = mysql.connector.connect(
            host=os.getenv("DB_HOST", "localhost"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME", "cafeteria_shop_cr")
        )

        cursor = conexao.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                p.id_pedido,
                c.nome AS nome_cliente,
                p.valor_total,
                p.status,
                pg.status_pagamento
            FROM pedido p
            INNER JOIN cliente c
                ON p.id_cliente = c.id_cliente
            LEFT JOIN pagamento pg
                ON p.id_pedido = pg.id_pedido
            ORDER BY p.id_pedido DESC
        """)

        pedidos = cursor.fetchall()

        return render_template(
            "painel_admin.html",
            pedidos=pedidos
        )

    except mysql.connector.Error:
        app.logger.exception("Erro ao consultar pedidos")
        return "Erro ao carregar os pedidos.", 500

    finally:
        if "cursor" in locals():
            cursor.close()
        if "conexao" in locals() and conexao.is_connected():
            conexao.close()
@app.route("/aprovar-pagamento/<int:id_pedido>", methods=["POST"])
def aprovar_pagamento(id_pedido):
    if not session.get("admin_id"):
        return redirect(url_for("login_admin"))

    conexao = None
    cursor = None

    try:
        conexao = mysql.connector.connect(
            host=os.getenv("DB_HOST", "localhost"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME", "cafeteria_shop_cr")
        )

        cursor = conexao.cursor()

        cursor.execute("""
            UPDATE pagamento
            SET status_pagamento = 'aprovado',
                data_pagamento = NOW()
            WHERE id_pedido = %s
              AND status_pagamento = 'pendente'
        """, (id_pedido,))

        if cursor.rowcount != 1:
            conexao.rollback()
            return "Pagamento pendente não encontrado.", 404

        cursor.execute("""
            UPDATE pedido
            SET status = 'confirmado'
            WHERE id_pedido = %s
              AND status = 'aguardando_pagamento'
        """, (id_pedido,))

        if cursor.rowcount != 1:
            conexao.rollback()
            return "Pedido não está aguardando pagamento.", 409

        conexao.commit()

        return redirect(url_for("painel_admin"))

    except mysql.connector.Error:
        if conexao is not None:
            conexao.rollback()

        app.logger.exception("Erro ao aprovar pagamento")
        return "Erro ao aprovar pagamento.", 500

    finally:
        if cursor is not None:
            cursor.close()

        if conexao is not None and conexao.is_connected():
            conexao.close()
@app.route("/logout-admin", methods=["POST"])
def logout_admin():
    session.clear()
    return redirect(url_for("login_admin"))
@app.route("/atualizar-status-pedido/<int:id_pedido>", methods=["POST"])
def atualizar_status_pedido(id_pedido):
    if not session.get("admin_id"):
        return redirect(url_for("login_admin"))

    novo_status = request.form.get("novo_status", "")

    transicoes = {
        "confirmado": "em_preparo",
        "em_preparo": "pronto",
        "pronto": "entregue"
    }

    conexao = None
    cursor = None

    try:
        conexao = mysql.connector.connect(
            host=os.getenv("DB_HOST", "localhost"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME", "cafeteria_shop_cr")
        )

        cursor = conexao.cursor(dictionary=True)

        cursor.execute("""
            SELECT p.status, pg.status_pagamento
            FROM pedido p
            LEFT JOIN pagamento pg
                ON p.id_pedido = pg.id_pedido
            WHERE p.id_pedido = %s
            FOR UPDATE
        """, (id_pedido,))

        pedido = cursor.fetchone()

        if not pedido:
            return "Pedido não encontrado.", 404

        if pedido["status_pagamento"] != "aprovado":
            return "O pagamento ainda não foi aprovado.", 403

        status_esperado = transicoes.get(pedido["status"])

        if novo_status != status_esperado:
            return "Transição de status não permitida.", 400

        cursor.execute("""
            UPDATE pedido
            SET status = %s
            WHERE id_pedido = %s
        """, (novo_status, id_pedido))

        conexao.commit()

        return redirect(url_for("painel_admin"))

    except mysql.connector.Error:
        if conexao is not None:
            conexao.rollback()
        app.logger.exception("Erro ao atualizar pedido")
        return "Erro ao atualizar pedido.", 500

    finally:
        if cursor is not None:
            cursor.close()
        if conexao is not None and conexao.is_connected():
            conexao.close()
@app.route("/login-cliente", methods=["GET", "POST"])
def login_cliente():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "")

        conexao = None
        cursor = None

        try:
            conexao = mysql.connector.connect(
                host=os.getenv("DB_HOST", "localhost"),
                user=os.getenv("DB_USER"),
                password=os.getenv("DB_PASSWORD"),
                database=os.getenv("DB_NAME", "cafeteria_shop_cr")
            )

            cursor = conexao.cursor(dictionary=True)

            cursor.execute("""
                SELECT id_cliente, nome, senha_hash
                FROM cliente
                WHERE email = %s
                LIMIT 1
            """, (email,))

            cliente = cursor.fetchone()

            if not cliente or not check_password_hash(
                cliente["senha_hash"], senha
            ):
                return render_template(
                    "login_cliente.html",
                    erro="E-mail ou senha incorretos."
                ), 401

            session.clear()
            session["cliente_id"] = cliente["id_cliente"]
            session["cliente_nome"] = cliente["nome"]

            return redirect(url_for("area_cliente"))

        except mysql.connector.Error:
            app.logger.exception("Erro no login do cliente")
            return "Erro ao realizar login.", 500

        finally:
            if cursor is not None:
                cursor.close()

            if conexao is not None and conexao.is_connected():
                conexao.close()

    return render_template("login_cliente.html")


@app.route("/area-cliente")
def area_cliente():
    cliente_id = session.get("cliente_id")

    if not cliente_id:
        return redirect(url_for("login_cliente"))

    conexao = None
    cursor = None

    try:
        conexao = mysql.connector.connect(
            host=os.getenv("DB_HOST", "localhost"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME", "cafeteria_shop_cr")
        )

        cursor = conexao.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                p.id_pedido,
                p.data_pedido,
                p.valor_total,
                p.status,
                pg.forma_pagamento,
                pg.status_pagamento
            FROM pedido p
            LEFT JOIN pagamento pg
                ON p.id_pedido = pg.id_pedido
            WHERE p.id_cliente = %s
            ORDER BY p.id_pedido DESC
        """, (cliente_id,))

        pedidos = cursor.fetchall()

        return render_template(
            "area_cliente.html",
            nome=session["cliente_nome"],
            pedidos=pedidos
        )

    except mysql.connector.Error:
        app.logger.exception("Erro ao consultar pedidos do cliente")
        return "Erro ao carregar seus pedidos.", 500

    finally:
        if cursor is not None:
            cursor.close()

        if conexao is not None and conexao.is_connected():
            conexao.close()
@app.route("/logout-cliente", methods=["POST"])
def logout_cliente():
    session.pop("cliente_id", None)
    session.pop("cliente_nome", None)
    return redirect(url_for("login_cliente"))


if __name__ == "__main__":
    app.run(debug=True)
