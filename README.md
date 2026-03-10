# Free Farm Backend

Backend da aplicação Free Farm desenvolvido com FastAPI.

## Instalação

### 1. Clonar o repositório
```bash
git clone https://github.com/seu-usuario/Free_Farm_Backend.git
cd Free_Farm_Backend
```

### 2. Criar ambiente virtual
```bash
python -m venv venv
```

### 3. Ativar ambiente virtual

**Windows:**
```bash
venv\Scripts\activate
```

**macOS/Linux:**
```bash
source venv/bin/activate
```

### 4. Instalar dependências
```bash
pip install -r requirements.txt
```

## Executar

```bash
uvicorn app.main:app --reload
```

A API estará disponível em: `http://localhost:8000`
Documentação: `http://localhost:8000/docs`

## Endpoints

- `POST /register` - Registrar novo jogador
- `POST /login` - Fazer login (retorna access token + refresh token)
- `POST /token/refresh` - Renovar sessao usando refresh token
- `POST /logout` - Invalidar sessao atual (access token + refresh token)
- `GET /me` - Obter dados do jogador autenticado
- `POST /wallet/deposit` - Depositar saldo na carteira do jogador autenticado
- `GET /wallet/history` - Consultar historico da carteira do jogador autenticado
- `GET /inventory/me` - Obter inventario estruturado do jogador autenticado
- `POST /inventory/items/add` - Adicionar item ao inventario do jogador autenticado
- `GET /land/me` - Obter grid de terreno do jogador autenticado
- `POST /land/plots` - Criar lote de terreno com coordenadas unicas por jogador
- `PATCH /land/plots/{plot_id}/state` - Atualizar estado do lote (empty, plowed, planted)

## Session Policy

- Access token expira em `ACCESS_TOKEN_EXPIRE_MINUTES` (padrao: 60).
- Refresh token expira em `REFRESH_TOKEN_EXPIRE_DAYS` (padrao: 7).
- `POST /token/refresh` faz rotacao de refresh token (o token antigo e revogado).
- `POST /logout` revoga o access token atual e o refresh token enviado.
- Tokens expirados ou revogados retornam `401 Unauthorized`.

## Estrutura do Projeto

```
app/
  ├── __init__.py
  ├── auth.py         # Lógica de autenticação
  ├── crud.py         # Operações de banco de dados
  ├── database.py     # Configuração do banco
  ├── main.py         # Endpoints da API
  ├── models.py       # Modelos SQLAlchemy
  └── schemas.py      # Schemas Pydantic
```
