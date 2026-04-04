"""
Sistema Completo de Almoxarifado - Versão 2.7.4
✅ Adicionado campo "Apelidos" no cadastro de itens
✅ Apelidos são considerados na busca por nome
✅ Fotos comprimidas e armazenadas no banco de dados SQLite
✅ Visualização ampliada ao clicar na miniatura
✅ Responsáveis agora aparecem na lista de colaboradores (saída múltipla)
✅ Setor do colaborador preenchido automaticamente ao selecionar na lista
✅ Fotos do item e do colaborador aparecem na tela de saída múltipla
✅ Duplo clique na foto abre versão ampliada
✅ Saída em itens com status "Em Compra" permitida
✅ Temas personalizáveis (claro, escuro, azul, amarelo) salvos nas configurações
✅ Foto do responsável na entrada e na saída múltipla (atualização dinâmica)
✅ Geração automática de apelidos para itens existentes (ferramenta na aba Configurações)
✅ Aba histórico exibe fotos do responsável e do colaborador
✅ Tamanhos das fotos padronizados (50×50 para pessoas, 80×80 para itens na saída)
✅ NOVO: Histórico pode ser filtrado por item específico (busca por código, nome ou apelido)
✅ INTEGRAÇÃO COM DASHBOARD: Notifica servidor Node.js após cada alteração
"""

import sys
import os
import sqlite3
import json
import csv
import shutil
import statistics
import unicodedata
import re
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Tuple, Any
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtPrintSupport import QPrintDialog, QPrinter
import base64
from io import BytesIO
from functools import partial
import requests  # <-- NOVO: para notificar o dashboard

# Tentar importar PIL para compressão de imagens
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("⚠️ PIL (Pillow) não instalado. As fotos não serão comprimidas.")

# ========== NOTIFICAÇÃO DO DASHBOARD ==========
def notificar_dashboard():
    """Envia uma notificação para o servidor Node.js do dashboard."""
    try:
        requests.post('http://localhost:3000/update', timeout=0.5)
    except Exception as e:
        print(f"Dashboard offline ou erro na notificação: {e}")

# ========== CONFIGURAÇÕES DE TIMEZONE ==========
try:
    from zoneinfo import ZoneInfo
    tz_brasil = ZoneInfo("America/Sao_Paulo")
except ImportError:
    import pytz
    tz_brasil = pytz.timezone("America/Sao_Paulo")

def utc_to_local_brasil(utc_dt_str: str) -> str:
    """Converte string de data/hora UTC para formato local brasileiro."""
    if not utc_dt_str:
        return ""
    try:
        dt_utc = datetime.strptime(utc_dt_str, "%Y-%m-%d %H:%M:%S")
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
        dt_local = dt_utc.astimezone(tz_brasil)
        return dt_local.strftime("%d/%m/%Y %H:%M")
    except:
        return utc_dt_str

# ========== DIRETÓRIOS ==========
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_DIR = os.path.join(BASE_DIR, 'data')
BACKUP_DIR = os.path.join(BASE_DIR, 'backups')
EXPORT_DIR = os.path.join(BASE_DIR, 'exportacoes')
REPORT_DIR = os.path.join(BASE_DIR, 'relatorios')

for directory in [DATA_DIR, BACKUP_DIR, EXPORT_DIR, REPORT_DIR]:
    if not os.path.exists(directory):
        os.makedirs(directory)

DATABASE_PATH = os.path.join(DATA_DIR, 'almoxarifado.db')

# ========== MODELOS ==========
@dataclass
class Item:
    id: Optional[int] = None
    codigo: str = ""
    nome_oficial: str = ""
    nome_fantasia: str = ""
    apelidos: str = ""
    categoria: str = ""
    descricao: str = ""
    status: str = "ativo"
    quantidade_minima: int = 0
    quantidade_atencao: Optional[int] = None
    unidade: str = "un"
    local_principal: str = ""
    local_alternativo: Optional[str] = None
    obs_localizacao: Optional[str] = None
    tem_validade: bool = False
    data_validade: Optional[str] = None
    estoque_atual: int = 0
    data_cadastro: Optional[str] = None
    data_atualizacao: Optional[str] = None
    foto: Optional[bytes] = None

    def calcular_status_estoque(self):
        if self.estoque_atual <= self.quantidade_minima:
            return "critico"
        elif self.quantidade_atencao and self.estoque_atual <= self.quantidade_atencao:
            return "atencao"
        else:
            return "normal"

@dataclass
class NomeCadastrado:
    id: Optional[int] = None
    nome: str = ""
    tipo: str = ""
    setor: Optional[str] = None
    email: Optional[str] = None
    telefone: Optional[str] = None
    observacoes: Optional[str] = None
    status: str = "ativo"
    data_cadastro: Optional[str] = None
    foto: Optional[bytes] = None

@dataclass
class Movimentacao:
    id: Optional[int] = None
    tipo: str = ""
    item_id: int = 0
    quantidade: int = 0
    responsavel: str = ""
    colaborador: Optional[str] = None
    setor_colaborador: Optional[str] = None
    fornecedor: Optional[str] = None
    nota_fiscal: Optional[str] = None
    observacoes: Optional[str] = None
    observacoes_item: Optional[str] = None
    data_movimentacao: Optional[str] = None

@dataclass
class SaidaMultipla:
    item_id: int
    codigo: str
    nome: str
    quantidade: int
    unidade: str
    observacoes_item: Optional[str] = None

@dataclass
class PrevisaoConsumo:
    item_id: int
    codigo: str
    nome: str
    consumo_medio: float
    desvio_padrao: float
    dias_restantes: float
    previsao_reposicao: str
    estoque_atual: int
    estoque_minimo: int
    status: str

# ========== BANCO DE DADOS ==========
class Database:
    def __init__(self, db_path=DATABASE_PATH):
        self.db_path = db_path
        self.conn = None
        self.cursor = None

    def connect(self):
        try:
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self.cursor = self.conn.cursor()
            print(f"✅ Banco de dados conectado: {self.db_path}")
            return True
        except Exception as e:
            print(f"❌ Erro ao conectar ao banco: {e}")
            return False

    def close(self):
        if self.conn:
            self.conn.close()

    def criar_tabelas(self):
        try:
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS itens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    codigo TEXT UNIQUE NOT NULL,
                    nome_oficial TEXT NOT NULL,
                    nome_fantasia TEXT NOT NULL,
                    apelidos TEXT,
                    categoria TEXT,
                    descricao TEXT,
                    status TEXT DEFAULT 'ativo',
                    quantidade_minima INTEGER DEFAULT 0,
                    quantidade_atencao INTEGER,
                    unidade TEXT DEFAULT 'un',
                    local_principal TEXT NOT NULL,
                    local_alternativo TEXT,
                    obs_localizacao TEXT,
                    tem_validade INTEGER DEFAULT 0,
                    data_validade DATE,
                    estoque_atual INTEGER DEFAULT 0,
                    data_cadastro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    data_atualizacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS nomes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome TEXT NOT NULL,
                    tipo TEXT NOT NULL,
                    setor TEXT,
                    email TEXT,
                    telefone TEXT,
                    observacoes TEXT,
                    status TEXT DEFAULT 'ativo',
                    data_cadastro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS movimentacoes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tipo TEXT NOT NULL,
                    item_id INTEGER NOT NULL,
                    quantidade INTEGER NOT NULL,
                    responsavel TEXT NOT NULL,
                    colaborador TEXT,
                    setor_colaborador TEXT,
                    fornecedor TEXT,
                    nota_fiscal TEXT,
                    observacoes TEXT,
                    observacoes_item TEXT,
                    data_movimentacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (item_id) REFERENCES itens (id)
                )
            ''')

            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS configuracoes (
                    chave TEXT PRIMARY KEY,
                    valor TEXT,
                    data_atualizacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            self.conn.commit()
            print("✅ Tabelas criadas/verificadas")
            return True
        except Exception as e:
            print(f"❌ Erro ao criar tabelas: {e}")
            return False

    def inicializar_dados(self):
        try:
            configs = [
                ('sistema_nome', 'Sistema de Almoxarifado'),
                ('sistema_versao', '2.7.4'),
                ('empresa_nome', 'Empresa'),
                ('ultimo_backup', 'Nunca'),
                ('total_itens', '0'),
                ('total_movimentacoes', '0'),
                ('limite_valor_absurdo', '1000'),
                ('dias_previsao', '30'),
            ]
            self.cursor.executemany(
                'INSERT OR REPLACE INTO configuracoes (chave, valor) VALUES (?, ?)',
                configs
            )
            self.conn.commit()
            return True
        except Exception as e:
            print(f"❌ Erro ao inicializar dados: {e}")
            return False

    def verificar_e_adicionar_colunas(self):
        """Adiciona colunas que podem estar faltando nas tabelas."""
        try:
            # Tabela itens - verificar coluna foto
            self.cursor.execute("PRAGMA table_info(itens)")
            colunas = [col[1] for col in self.cursor.fetchall()]
            if 'foto' not in colunas:
                self.cursor.execute("ALTER TABLE itens ADD COLUMN foto BLOB")
                print("✅ Coluna 'foto' adicionada à tabela itens.")

            # Tabela itens - verificar coluna apelidos
            if 'apelidos' not in colunas:
                self.cursor.execute("ALTER TABLE itens ADD COLUMN apelidos TEXT")
                print("✅ Coluna 'apelidos' adicionada à tabela itens.")

            # Tabela nomes - verificar coluna foto
            self.cursor.execute("PRAGMA table_info(nomes)")
            colunas = [col[1] for col in self.cursor.fetchall()]
            if 'foto' not in colunas:
                self.cursor.execute("ALTER TABLE nomes ADD COLUMN foto BLOB")
                print("✅ Coluna 'foto' adicionada à tabela nomes.")

            self.conn.commit()
        except Exception as e:
            print(f"⚠️ Erro ao verificar/adicionar colunas: {e}")

    def criar_backup(self):
        try:
            data_atual = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_file = os.path.join(BACKUP_DIR, f'backup_{data_atual}.db')
            dest_conn = sqlite3.connect(backup_file)
            self.conn.backup(dest_conn)
            dest_conn.close()
            self.cursor.execute('SELECT COUNT(*) as total FROM itens')
            total_itens = self.cursor.fetchone()['total']
            self.cursor.execute('SELECT COUNT(*) as total FROM movimentacoes')
            total_movimentacoes = self.cursor.fetchone()['total']
            self.cursor.execute(
                'UPDATE configuracoes SET valor = ? WHERE chave = ?',
                (datetime.now().strftime('%d/%m/%Y %H:%M'), 'ultimo_backup')
            )
            self.conn.commit()
            return True, backup_file, data_atual
        except Exception as e:
            print(f"❌ Erro ao criar backup: {e}")
            return False, str(e), None

    def listar_backups(self):
        try:
            backups = []
            if os.path.exists(BACKUP_DIR):
                for arquivo in os.listdir(BACKUP_DIR):
                    if arquivo.endswith('.db'):
                        caminho = os.path.join(BACKUP_DIR, arquivo)
                        stats = os.stat(caminho)
                        tamanho = stats.st_size / (1024 * 1024)
                        data_mod = datetime.fromtimestamp(stats.st_mtime)
                        backups.append({
                            'arquivo': arquivo,
                            'caminho': caminho,
                            'tamanho': f"{tamanho:.2f} MB",
                            'data': data_mod.strftime('%d/%m/%Y %H:%M')
                        })
            backups.sort(key=lambda x: x['data'], reverse=True)
            return backups
        except Exception as e:
            print(f"❌ Erro ao listar backups: {e}")
            return []

    def importar_backup_json(self, caminho_json: str) -> Tuple[bool, str]:
        try:
            with open(caminho_json, 'r', encoding='utf-8') as f:
                dados = json.load(f)
            if 'itens' not in dados or 'movimentacoes' not in dados:
                return False, "Arquivo JSON inválido: chaves 'itens' e 'movimentacoes' não encontradas."
            self.cursor.execute('BEGIN TRANSACTION')
            itens_importados = 0
            for item_data in dados['itens']:
                status_item = item_data.get('statusItem', 'ativo')
                tem_validade = 1 if item_data.get('temValidade') else 0
                data_validade = item_data.get('validade')
                if data_validade and data_validade != 'null':
                    data_validade = data_validade.split('T')[0] if 'T' in data_validade else data_validade
                else:
                    data_validade = None
                self.cursor.execute('''
                    INSERT OR REPLACE INTO itens (
                        id, codigo, nome_oficial, nome_fantasia, apelidos, categoria, descricao,
                        status, quantidade_minima, quantidade_atencao, unidade,
                        local_principal, local_alternativo, obs_localizacao,
                        tem_validade, data_validade, estoque_atual
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    item_data.get('id'),
                    item_data['codigo'],
                    item_data.get('nomeOficial', ''),
                    item_data.get('nomeFantasia', ''),
                    item_data.get('apelidos', ''),
                    item_data.get('categoria', ''),
                    item_data.get('descricao', ''),
                    status_item,
                    item_data.get('quantidadeMinima', 0),
                    item_data.get('quantidadeAtencao'),
                    item_data.get('unidade', 'un'),
                    item_data.get('localPrincipal', ''),
                    item_data.get('localAlternativo'),
                    item_data.get('obsLocalizacao'),
                    tem_validade,
                    data_validade,
                    item_data.get('estoqueAtual', 0)
                ))
                itens_importados += 1
            mov_importadas = 0
            for mov_data in dados['movimentacoes']:
                self.cursor.execute('SELECT id FROM itens WHERE id = ?', (mov_data.get('itemId'),))
                if not self.cursor.fetchone():
                    continue
                tipo = mov_data.get('tipo')
                if tipo not in ('entrada', 'saida'):
                    continue
                data_mov = mov_data.get('dataHora') or mov_data.get('data')
                if data_mov:
                    data_mov = data_mov.replace('T', ' ').split('.')[0]
                else:
                    data_mov = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                self.cursor.execute('''
                    INSERT INTO movimentacoes (
                        tipo, item_id, quantidade, responsavel, colaborador,
                        setor_colaborador, fornecedor, nota_fiscal, observacoes,
                        observacoes_item, data_movimentacao
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    tipo,
                    mov_data.get('itemId'),
                    mov_data.get('quantidade', 0),
                    mov_data.get('responsavel', ''),
                    mov_data.get('colaborador') or mov_data.get('funcionarioRetirou'),
                    mov_data.get('setor_colaborador') or mov_data.get('departamento'),
                    mov_data.get('fornecedor'),
                    None,
                    mov_data.get('observacoes'),
                    None,
                    data_mov
                ))
                mov_importadas += 1
            self.cursor.execute('UPDATE configuracoes SET valor = ? WHERE chave = ?', (str(itens_importados), 'total_itens'))
            self.cursor.execute('UPDATE configuracoes SET valor = ? WHERE chave = ?', (str(mov_importadas), 'total_movimentacoes'))
            self.conn.commit()
            notificar_dashboard()  # <-- NOTIFICAR DASHBOARD
            return True, f"Importação concluída: {itens_importados} itens e {mov_importadas} movimentações importadas."
        except Exception as e:
            self.conn.rollback()
            return False, f"Erro durante a importação: {str(e)}"

    def renumerar_itens(self, ordem: str) -> Tuple[bool, str]:
        try:
            if ordem == 'data_cadastro':
                order_by = 'data_cadastro ASC'
            else:
                order_by = 'id ASC'
            self.cursor.execute(f'SELECT id FROM itens ORDER BY {order_by}')
            itens = self.cursor.fetchall()
            if not itens:
                return False, "Nenhum item encontrado para renumerar."
            total = len(itens)
            num_digitos = max(4, len(str(total)))
            formato = f"{{:0{num_digitos}d}}"
            self.cursor.execute('BEGIN TRANSACTION')
            for idx, item in enumerate(itens, start=1):
                novo_codigo = formato.format(idx)
                self.cursor.execute(
                    'UPDATE itens SET codigo = ? WHERE id = ?',
                    (novo_codigo, item['id'])
                )
            self.conn.commit()
            notificar_dashboard()  # <-- NOTIFICAR DASHBOARD
            return True, f"{total} itens renumerados com sucesso (formato {num_digitos} dígitos)."
        except Exception as e:
            self.conn.rollback()
            return False, f"Erro durante a renumeracão: {str(e)}"

# ========== SISTEMA ==========
class SistemaAlmoxarifado:
    def __init__(self, db: Database):
        self.db = db

    def cadastrar_item(self, item: Item) -> Tuple[bool, str]:
        try:
            self.db.cursor.execute('SELECT id FROM itens WHERE codigo = ?', (item.codigo,))
            if self.db.cursor.fetchone():
                return False, f"Código '{item.codigo}' já existe!"
            self.db.cursor.execute('''
                INSERT INTO itens (
                    codigo, nome_oficial, nome_fantasia, apelidos, categoria, descricao,
                    status, quantidade_minima, quantidade_atencao, unidade,
                    local_principal, local_alternativo, obs_localizacao,
                    tem_validade, data_validade, estoque_atual, foto
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                item.codigo, item.nome_oficial, item.nome_fantasia, item.apelidos,
                item.categoria, item.descricao, item.status, item.quantidade_minima,
                item.quantidade_atencao, item.unidade, item.local_principal,
                item.local_alternativo, item.obs_localizacao,
                1 if item.tem_validade else 0, item.data_validade, item.estoque_atual,
                item.foto
            ))
            self.db.cursor.execute(
                'UPDATE configuracoes SET valor = CAST(valor AS INTEGER) + 1 WHERE chave = ?',
                ('total_itens',)
            )
            self.db.conn.commit()
            notificar_dashboard()  # <-- NOTIFICAR DASHBOARD
            return True, f"Item cadastrado com sucesso!"
        except Exception as e:
            return False, f"Erro ao cadastrar item: {str(e)}"

    def atualizar_item(self, item: Item) -> Tuple[bool, str]:
        try:
            self.db.cursor.execute('''
                UPDATE itens SET
                    codigo = ?,
                    nome_oficial = ?,
                    nome_fantasia = ?,
                    apelidos = ?,
                    categoria = ?,
                    descricao = ?,
                    status = ?,
                    quantidade_minima = ?,
                    quantidade_atencao = ?,
                    unidade = ?,
                    local_principal = ?,
                    local_alternativo = ?,
                    obs_localizacao = ?,
                    tem_validade = ?,
                    data_validade = ?,
                    estoque_atual = ?,
                    foto = ?,
                    data_atualizacao = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (
                item.codigo, item.nome_oficial, item.nome_fantasia, item.apelidos,
                item.categoria, item.descricao, item.status, item.quantidade_minima,
                item.quantidade_atencao, item.unidade, item.local_principal,
                item.local_alternativo, item.obs_localizacao,
                1 if item.tem_validade else 0, item.data_validade, item.estoque_atual,
                item.foto, item.id
            ))
            self.db.conn.commit()
            notificar_dashboard()  # <-- NOTIFICAR DASHBOARD
            return True, "Item atualizado com sucesso!"
        except Exception as e:
            return False, f"Erro ao atualizar item: {str(e)}"

    def buscar_item(self, criterio: str, valor: str) -> List[Item]:
        try:
            query = ''
            params = ()
            if criterio == 'codigo':
                query = 'SELECT * FROM itens WHERE codigo LIKE ? ORDER BY nome_oficial'
                params = (f'%{valor}%',)
            elif criterio == 'codigo_exato':
                query = 'SELECT * FROM itens WHERE codigo = ?'
                params = (valor,)
            elif criterio == 'nome':
                query = '''SELECT * FROM itens 
                           WHERE nome_oficial LIKE ? 
                              OR nome_fantasia LIKE ? 
                              OR apelidos LIKE ? 
                           ORDER BY nome_oficial'''
                params = (f'%{valor}%', f'%{valor}%', f'%{valor}%')
            elif criterio == 'ativos':
                query = 'SELECT * FROM itens WHERE status = "ativo" ORDER BY nome_oficial'
            elif criterio == 'em_compra':
                query = 'SELECT * FROM itens WHERE status = "em_compra" ORDER BY nome_oficial'
            elif criterio == 'inativos':
                query = 'SELECT * FROM itens WHERE status = "inativo" ORDER BY nome_oficial'
            elif criterio == 'todos':
                query = 'SELECT * FROM itens ORDER BY nome_oficial'
            elif criterio == 'criticos':
                query = '''
                    SELECT * FROM itens 
                    WHERE status = "ativo" AND estoque_atual <= quantidade_minima 
                    ORDER BY estoque_atual
                '''
            elif criterio == 'atencao':
                query = '''
                    SELECT * FROM itens 
                    WHERE status = "ativo" AND quantidade_atencao IS NOT NULL 
                    AND estoque_atual <= quantidade_atencao AND estoque_atual > quantidade_minima
                    ORDER BY estoque_atual
                '''
            elif criterio == 'validade':
                data_limite = (datetime.now() + timedelta(days=90)).strftime('%Y-%m-%d')
                query = '''
                    SELECT * FROM itens 
                    WHERE tem_validade = 1 AND data_validade <= ? 
                    ORDER BY data_validade
                '''
                params = (data_limite,)
            elif criterio == 'categoria':
                query = 'SELECT * FROM itens WHERE categoria = ? ORDER BY nome_oficial'
                params = (valor,)
            else:
                return []

            self.db.cursor.execute(query, params)
            rows = self.db.cursor.fetchall()

            itens = []
            for row in rows:
                item = Item(
                    id=row['id'],
                    codigo=row['codigo'],
                    nome_oficial=row['nome_oficial'],
                    nome_fantasia=row['nome_fantasia'],
                    apelidos=row['apelidos'] if 'apelidos' in row.keys() else "",
                    categoria=row['categoria'],
                    descricao=row['descricao'],
                    status=row['status'],
                    quantidade_minima=row['quantidade_minima'],
                    quantidade_atencao=row['quantidade_atencao'],
                    unidade=row['unidade'],
                    local_principal=row['local_principal'],
                    local_alternativo=row['local_alternativo'],
                    obs_localizacao=row['obs_localizacao'],
                    tem_validade=bool(row['tem_validade']),
                    data_validade=row['data_validade'],
                    estoque_atual=row['estoque_atual'],
                    foto=row['foto'] if 'foto' in row.keys() else None
                )
                itens.append(item)
            return itens
        except Exception as e:
            print(f"❌ Erro na busca: {e}")
            return []

    def registrar_movimentacao(self, mov: Movimentacao) -> Tuple[bool, str]:
        try:
            self.db.cursor.execute(
                'SELECT estoque_atual, status, quantidade_minima FROM itens WHERE id = ?',
                (mov.item_id,)
            )
            item = self.db.cursor.fetchone()
            if not item:
                return False, "Item não encontrado!"
            estoque_atual = item['estoque_atual']
            status_atual = item['status']
            quantidade_minima = item['quantidade_minima']
            if mov.tipo == 'saida' and estoque_atual < mov.quantidade:
                return False, f"Estoque insuficiente! Disponível: {estoque_atual}"
            self.db.cursor.execute('''
                INSERT INTO movimentacoes (
                    tipo, item_id, quantidade, responsavel, colaborador,
                    setor_colaborador, fornecedor, nota_fiscal,
                    observacoes, observacoes_item
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                mov.tipo, mov.item_id, mov.quantidade, mov.responsavel,
                mov.colaborador, mov.setor_colaborador, mov.fornecedor,
                mov.nota_fiscal, mov.observacoes, mov.observacoes_item
            ))
            novo_estoque = estoque_atual + (mov.quantidade if mov.tipo == 'entrada' else -mov.quantidade)
            self.db.cursor.execute(
                'UPDATE itens SET estoque_atual = ?, data_atualizacao = CURRENT_TIMESTAMP WHERE id = ?',
                (novo_estoque, mov.item_id)
            )
            if mov.tipo == 'entrada' and status_atual == 'em_compra' and novo_estoque > quantidade_minima:
                self.db.cursor.execute(
                    'UPDATE itens SET status = "ativo" WHERE id = ?',
                    (mov.item_id,)
                )
            self.db.cursor.execute(
                'UPDATE configuracoes SET valor = CAST(valor AS INTEGER) + 1 WHERE chave = ?',
                ('total_movimentacoes',)
            )
            self.db.conn.commit()
            notificar_dashboard()  # <-- NOTIFICAR DASHBOARD
            tipo_str = "ENTRADA" if mov.tipo == 'entrada' else "SAÍDA"
            return True, f"{tipo_str} registrada! Novo estoque: {novo_estoque}"
        except Exception as e:
            return False, f"Erro ao registrar: {str(e)}"

    def registrar_saida_multipla(self, itens_saida: List[SaidaMultipla], responsavel: str, colaborador: str, setor: str = None, observacoes: str = None) -> Tuple[bool, str, List[str]]:
        try:
            erros = []
            sucessos = []
            for item_saida in itens_saida:
                self.db.cursor.execute(
                    'SELECT estoque_atual FROM itens WHERE id = ?',
                    (item_saida.item_id,)
                )
                item = self.db.cursor.fetchone()
                if not item:
                    erros.append(f"Item {item_saida.codigo} não encontrado!")
                    continue
                estoque_atual = item['estoque_atual']
                if estoque_atual < item_saida.quantidade:
                    erros.append(f"Estoque insuficiente para {item_saida.codigo}! Disponível: {estoque_atual}")
                    continue
                self.db.cursor.execute('''
                    INSERT INTO movimentacoes (
                        tipo, item_id, quantidade, responsavel, colaborador,
                        setor_colaborador, observacoes, observacoes_item
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    'saida', item_saida.item_id, item_saida.quantidade, responsavel,
                    colaborador, setor, observacoes, item_saida.observacoes_item
                ))
                novo_estoque = estoque_atual - item_saida.quantidade
                self.db.cursor.execute(
                    'UPDATE itens SET estoque_atual = ?, data_atualizacao = CURRENT_TIMESTAMP WHERE id = ?',
                    (novo_estoque, item_saida.item_id)
                )
                self.db.cursor.execute(
                    'UPDATE configuracoes SET valor = CAST(valor AS INTEGER) + 1 WHERE chave = ?',
                    ('total_movimentacoes',)
                )
                sucessos.append(f"{item_saida.codigo}: {item_saida.quantidade} {item_saida.unidade}")
            self.db.conn.commit()
            notificar_dashboard()  # <-- NOTIFICAR DASHBOARD
            if erros:
                return False, "Erros encontrados:", erros + sucessos
            else:
                return True, f"Saída registrada para {len(sucessos)} itens!", sucessos
        except Exception as e:
            return False, f"Erro ao registrar saída múltipla: {str(e)}", []

    def buscar_movimentacoes(self, filtros: Dict = None) -> List[Dict]:
        try:
            query = '''
                SELECT m.*, i.codigo, i.nome_oficial, i.nome_fantasia 
                FROM movimentacoes m
                JOIN itens i ON m.item_id = i.id
                WHERE 1=1
            '''
            params = []
            if filtros:
                if 'tipo' in filtros and filtros['tipo']:
                    query += ' AND m.tipo = ?'
                    params.append(filtros['tipo'])
                if 'item_id' in filtros and filtros['item_id']:
                    query += ' AND m.item_id = ?'
                    params.append(filtros['item_id'])
                if 'responsavel' in filtros and filtros['responsavel']:
                    query += ' AND m.responsavel LIKE ?'
                    params.append(f'%{filtros["responsavel"]}%')
                if 'data_inicio' in filtros and filtros['data_inicio']:
                    query += ' AND DATE(m.data_movimentacao) >= ?'
                    params.append(filtros['data_inicio'])
                if 'data_fim' in filtros and filtros['data_fim']:
                    query += ' AND DATE(m.data_movimentacao) <= ?'
                    params.append(filtros['data_fim'])
            query += ' ORDER BY m.data_movimentacao DESC'
            self.db.cursor.execute(query, params)
            rows = self.db.cursor.fetchall()
            movimentacoes = []
            for row in rows:
                mov = {
                    'id': row['id'],
                    'tipo': row['tipo'],
                    'item_codigo': row['codigo'],
                    'item_nome': row['nome_oficial'],
                    'item_fantasia': row['nome_fantasia'],
                    'quantidade': row['quantidade'],
                    'responsavel': row['responsavel'],
                    'colaborador': row['colaborador'],
                    'setor_colaborador': row['setor_colaborador'],
                    'fornecedor': row['fornecedor'],
                    'nota_fiscal': row['nota_fiscal'],
                    'observacoes': row['observacoes'],
                    'data_movimentacao': row['data_movimentacao']
                }
                movimentacoes.append(mov)
            return movimentacoes
        except Exception as e:
            print(f"❌ Erro ao buscar movimentações: {e}")
            return []

    def cadastrar_nome(self, nome: NomeCadastrado) -> Tuple[bool, str]:
        try:
            self.db.cursor.execute('''
                INSERT INTO nomes (nome, tipo, setor, email, telefone, observacoes, status, foto)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                nome.nome, nome.tipo, nome.setor,
                nome.email, nome.telefone, nome.observacoes, nome.status, nome.foto
            ))
            self.db.conn.commit()
            notificar_dashboard()  # <-- NOTIFICAR DASHBOARD
            return True, "Nome cadastrado com sucesso!"
        except Exception as e:
            return False, f"Erro ao cadastrar nome: {str(e)}"

    def atualizar_nome(self, nome: NomeCadastrado) -> Tuple[bool, str]:
        try:
            self.db.cursor.execute('''
                UPDATE nomes SET
                    nome = ?,
                    tipo = ?,
                    setor = ?,
                    email = ?,
                    telefone = ?,
                    observacoes = ?,
                    status = ?,
                    foto = ?
                WHERE id = ?
            ''', (
                nome.nome, nome.tipo, nome.setor,
                nome.email, nome.telefone, nome.observacoes, nome.status,
                nome.foto, nome.id
            ))
            self.db.conn.commit()
            notificar_dashboard()  # <-- NOTIFICAR DASHBOARD
            return True, "Nome atualizado com sucesso!"
        except Exception as e:
            return False, f"Erro ao atualizar nome: {str(e)}"

    def excluir_nome(self, nome_id: int) -> Tuple[bool, str]:
        try:
            self.db.cursor.execute(
                'SELECT COUNT(*) as total FROM movimentacoes WHERE responsavel IN (SELECT nome FROM nomes WHERE id = ?) OR colaborador IN (SELECT nome FROM nomes WHERE id = ?)',
                (nome_id, nome_id)
            )
            uso = self.db.cursor.fetchone()['total']
            if uso > 0:
                return False, f"Não é possível excluir! Este nome está sendo usado em {uso} movimentação(ões)."
            self.db.cursor.execute('DELETE FROM nomes WHERE id = ?', (nome_id,))
            self.db.conn.commit()
            notificar_dashboard()  # <-- NOTIFICAR DASHBOARD
            return True, "Nome excluído com sucesso!"
        except Exception as e:
            return False, f"Erro ao excluir nome: {str(e)}"

    def buscar_nomes(self, tipo: str = None, status: str = None) -> List[NomeCadastrado]:
        try:
            query = 'SELECT * FROM nomes WHERE 1=1'
            params = []
            if tipo:
                query += ' AND tipo = ?'
                params.append(tipo)
            if status:
                query += ' AND status = ?'
                params.append(status)
            query += ' ORDER BY nome'
            self.db.cursor.execute(query, params)
            rows = self.db.cursor.fetchall()
            nomes = []
            for row in rows:
                nome = NomeCadastrado(
                    id=row['id'],
                    nome=row['nome'],
                    tipo=row['tipo'],
                    setor=row['setor'],
                    email=row['email'],
                    telefone=row['telefone'],
                    observacoes=row['observacoes'],
                    status=row['status'],
                    foto=row['foto'] if 'foto' in row.keys() else None
                )
                nomes.append(nome)
            return nomes
        except Exception as e:
            print(f"❌ Erro ao buscar nomes: {e}")
            return []

    def buscar_nome_por_nome(self, nome_exato: str) -> Optional[NomeCadastrado]:
        """Retorna o primeiro nome cadastrado com o nome exato (case insensitive)"""
        try:
            self.db.cursor.execute(
                'SELECT * FROM nomes WHERE nome = ? COLLATE NOCASE',
                (nome_exato.strip(),)
            )
            row = self.db.cursor.fetchone()
            if row:
                return NomeCadastrado(
                    id=row['id'],
                    nome=row['nome'],
                    tipo=row['tipo'],
                    setor=row['setor'],
                    email=row['email'],
                    telefone=row['telefone'],
                    observacoes=row['observacoes'],
                    status=row['status'],
                    foto=row['foto'] if 'foto' in row.keys() else None
                )
            return None
        except Exception as e:
            print(f"Erro ao buscar nome por nome: {e}")
            return None

    def obter_estatisticas(self) -> Dict:
        try:
            stats = {}
            self.db.cursor.execute('SELECT COUNT(*) as total FROM itens')
            stats['total_itens'] = self.db.cursor.fetchone()['total']
            self.db.cursor.execute('SELECT COUNT(*) as total FROM itens WHERE status = "ativo"')
            stats['itens_ativos'] = self.db.cursor.fetchone()['total']
            self.db.cursor.execute('SELECT COUNT(*) as total FROM itens WHERE status = "em_compra"')
            stats['itens_em_compra'] = self.db.cursor.fetchone()['total']
            self.db.cursor.execute('''
                SELECT COUNT(*) as total FROM itens 
                WHERE status = "ativo" AND estoque_atual <= quantidade_minima
            ''')
            stats['itens_criticos'] = self.db.cursor.fetchone()['total']
            self.db.cursor.execute('''
                SELECT COUNT(*) as total FROM itens 
                WHERE status = "ativo" AND quantidade_atencao IS NOT NULL 
                AND estoque_atual <= quantidade_atencao AND estoque_atual > quantidade_minima
            ''')
            stats['itens_atencao'] = self.db.cursor.fetchone()['total']
            data_limite = (datetime.now() + timedelta(days=90)).strftime('%Y-%m-%d')
            self.db.cursor.execute('''
                SELECT COUNT(*) as total FROM itens 
                WHERE tem_validade = 1 AND data_validade <= ?
            ''', (data_limite,))
            stats['itens_validade'] = self.db.cursor.fetchone()['total']
            self.db.cursor.execute('SELECT COUNT(*) as total FROM movimentacoes')
            stats['total_movimentacoes'] = self.db.cursor.fetchone()['total']
            self.db.cursor.execute(
                'SELECT valor FROM configuracoes WHERE chave = ?',
                ('ultimo_backup',)
            )
            resultado = self.db.cursor.fetchone()
            stats['ultimo_backup'] = resultado['valor'] if resultado else None
            return stats
        except Exception as e:
            print(f"❌ Erro ao obter estatísticas: {e}")
            return {}

    def calcular_consumo_medio(self, item_id: int, dias: int = 90) -> Dict:
        try:
            data_limite = (datetime.now() - timedelta(days=dias)).strftime('%Y-%m-%d')
            self.db.cursor.execute('''
                SELECT quantidade, DATE(data_movimentacao) as data 
                FROM movimentacoes 
                WHERE item_id = ? 
                AND tipo = 'saida' 
                AND DATE(data_movimentacao) >= ?
                ORDER BY data_movimentacao
            ''', (item_id, data_limite))
            saidas = self.db.cursor.fetchall()
            if not saidas:
                return {
                    'consumo_medio': 0,
                    'consumo_diario': 0,
                    'total_periodo': 0,
                    'dias_com_saida': 0,
                    'desvio_padrao': 0,
                    'valores_filtrados': [],
                    'valores_absurdos': []
                }
            self.db.cursor.execute('SELECT valor FROM configuracoes WHERE chave = ?', ('limite_valor_absurdo',))
            resultado = self.db.cursor.fetchone()
            limite_absurdo = float(resultado['valor']) if resultado else 1000
            consumos_por_dia = {}
            for saida in saidas:
                data = saida['data']
                quantidade = saida['quantidade']
                consumos_por_dia[data] = consumos_por_dia.get(data, 0) + quantidade
            valores_diarios = list(consumos_por_dia.values())
            valores_filtrados = [v for v in valores_diarios if v <= limite_absurdo]
            valores_absurdos = [v for v in valores_diarios if v > limite_absurdo]
            if not valores_filtrados and valores_absurdos:
                valores_filtrados = valores_absurdos.copy()
                valores_absurdos = []
            if valores_filtrados:
                consumo_total = sum(valores_filtrados)
                consumo_medio = consumo_total / len(valores_filtrados)
                consumo_diario = consumo_total / dias
                desvio_padrao = statistics.stdev(valores_filtrados) if len(valores_filtrados) > 1 else 0
            else:
                consumo_total = 0
                consumo_medio = 0
                consumo_diario = 0
                desvio_padrao = 0
            return {
                'consumo_medio': consumo_medio,
                'consumo_diario': consumo_diario,
                'total_periodo': consumo_total,
                'dias_com_saida': len(valores_filtrados),
                'desvio_padrao': desvio_padrao,
                'valores_filtrados': valores_filtrados,
                'valores_absurdos': valores_absurdos,
                'limite_absurdo': limite_absurdo
            }
        except Exception as e:
            print(f"❌ Erro ao calcular consumo: {e}")
            return {
                'consumo_medio': 0,
                'consumo_diario': 0,
                'total_periodo': 0,
                'dias_com_saida': 0,
                'desvio_padrao': 0,
                'valores_filtrados': [],
                'valores_absurdos': []
            }

    def prever_consumo_futuro(self, item_id: int, dias_previsao: int = 30) -> Dict:
        try:
            consumo_atual = self.calcular_consumo_medio(item_id)
            if consumo_atual['consumo_diario'] == 0:
                return {
                    'previsao_total': 0,
                    'previsao_diaria': 0,
                    'dias_restantes': float('inf'),
                    'estoque_atual': 0,
                    'estoque_minimo': 0,
                    'status': 'sem_consumo',
                    'mensagem': 'Sem histórico de consumo',
                    'consumo_diario': 0,
                    'desvio_padrao': 0
                }
            self.db.cursor.execute('SELECT estoque_atual, quantidade_minima FROM itens WHERE id = ?', (item_id,))
            item = self.db.cursor.fetchone()
            if not item:
                return {
                    'previsao_total': 0,
                    'previsao_diaria': 0,
                    'dias_restantes': 0,
                    'status': 'erro',
                    'mensagem': 'Item não encontrado'
                }
            estoque_atual = item['estoque_atual']
            estoque_minimo = item['quantidade_minima']
            if consumo_atual['consumo_diario'] > 0:
                dias_restantes = max(0, (estoque_atual - estoque_minimo) / consumo_atual['consumo_diario'])
            else:
                dias_restantes = float('inf')
            previsao_diaria = consumo_atual['consumo_diario']
            previsao_total = previsao_diaria * dias_previsao
            if dias_restantes < 7:
                status = 'urgente'
                mensagem = f'Estoque acabará em {dias_restantes:.1f} dias'
            elif dias_restantes < 30:
                status = 'atencao'
                mensagem = f'Estoque durará {dias_restantes:.1f} dias'
            else:
                status = 'normal'
                mensagem = f'Estoque suficiente para {dias_restantes:.1f} dias'
            if consumo_atual['dias_com_saida'] == 0:
                status = 'ocioso'
                mensagem = 'Sem consumo nos últimos 90 dias'
            return {
                'previsao_total': previsao_total,
                'previsao_diaria': previsao_diaria,
                'dias_restantes': dias_restantes,
                'estoque_atual': estoque_atual,
                'estoque_minimo': estoque_minimo,
                'status': status,
                'mensagem': mensagem,
                'consumo_diario': consumo_atual['consumo_diario'],
                'desvio_padrao': consumo_atual['desvio_padrao']
            }
        except Exception as e:
            print(f"❌ Erro ao prever consumo: {e}")
            return {
                'previsao_total': 0,
                'previsao_diaria': 0,
                'dias_restantes': 0,
                'status': 'erro',
                'mensagem': f'Erro: {str(e)}'
            }

    def gerar_relatorio_previsao_completo(self) -> List[PrevisaoConsumo]:
        try:
            itens = self.buscar_item('ativos', '')
            previsoes = []
            for item in itens:
                previsao = self.prever_consumo_futuro(item.id)
                previsao_obj = PrevisaoConsumo(
                    item_id=item.id,
                    codigo=item.codigo,
                    nome=item.nome_fantasia,
                    consumo_medio=previsao.get('consumo_diario', 0),
                    desvio_padrao=previsao.get('desvio_padrao', 0),
                    dias_restantes=previsao.get('dias_restantes', 0),
                    previsao_reposicao=previsao.get('mensagem', ''),
                    estoque_atual=previsao.get('estoque_atual', 0),
                    estoque_minimo=item.quantidade_minima,
                    status=previsao.get('status', 'normal')
                )
                previsoes.append(previsao_obj)
            ordem_status = {'urgente': 0, 'atencao': 1, 'normal': 2, 'ocioso': 3, 'erro': 4}
            previsoes.sort(key=lambda x: (ordem_status.get(x.status, 99), x.dias_restantes))
            return previsoes
        except Exception as e:
            print(f"❌ Erro ao gerar relatório de previsão: {e}")
            return []

    def obter_historico_consumo_grafico(self, item_id: int, dias: int = 90) -> Dict:
        try:
            data_limite = (datetime.now() - timedelta(days=dias)).strftime('%Y-%m-%d')
            self.db.cursor.execute('''
                SELECT 
                    DATE(data_movimentacao) as data,
                    SUM(quantidade) as total_dia
                FROM movimentacoes 
                WHERE item_id = ? 
                AND tipo = 'saida' 
                AND DATE(data_movimentacao) >= ?
                GROUP BY DATE(data_movimentacao)
                ORDER BY data
            ''', (item_id, data_limite))
            dados = self.db.cursor.fetchall()
            self.db.cursor.execute('SELECT codigo, nome_fantasia FROM itens WHERE id = ?', (item_id,))
            item = self.db.cursor.fetchone()
            datas = []
            valores = []
            for dado in dados:
                data_obj = datetime.strptime(dado['data'], '%Y-%m-%d')
                datas.append(data_obj.strftime('%d/%m'))
                valores.append(dado['total_dia'])
            media_movel = []
            if len(valores) >= 7:
                for i in range(len(valores)):
                    inicio = max(0, i - 3)
                    fim = min(len(valores), i + 4)
                    media = sum(valores[inicio:fim]) / (fim - inicio)
                    media_movel.append(media)
            else:
                media_movel = valores
            return {
                'item_codigo': item['codigo'] if item else '',
                'item_nome': item['nome_fantasia'] if item else '',
                'datas': datas,
                'valores': valores,
                'media_movel': media_movel,
                'total_periodo': sum(valores),
                'dias_com_dados': len(dados)
            }
        except Exception as e:
            print(f"❌ Erro ao obter histórico gráfico: {e}")
            return {
                'item_codigo': '',
                'item_nome': '',
                'datas': [],
                'valores': [],
                'media_movel': [],
                'total_periodo': 0,
                'dias_com_dados': 0
            }

# ========== FUNÇÕES AUXILIARES PARA IMAGENS ==========
def comprimir_imagem(caminho_arquivo: str, max_size: int = 800, quality: int = 80) -> Optional[bytes]:
    try:
        if PIL_AVAILABLE:
            with Image.open(caminho_arquivo) as img:
                if img.mode in ('RGBA', 'P'):
                    img = img.convert('RGB')
                img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
                buffer = BytesIO()
                img.save(buffer, format='JPEG', quality=quality, optimize=True)
                return buffer.getvalue()
        else:
            with open(caminho_arquivo, 'rb') as f:
                return f.read()
    except Exception as e:
        print(f"❌ Erro ao processar imagem: {e}")
        return None

def bytes_para_qpixmap(dados_bytes: bytes, max_width: int = 100, max_height: int = 100) -> QPixmap:
    pixmap = QPixmap()
    if dados_bytes:
        pixmap.loadFromData(dados_bytes)
        if not pixmap.isNull():
            return pixmap.scaled(max_width, max_height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return QPixmap(max_width, max_height)

# ========== WIDGETS PERSONALIZADOS ==========
class CampoAutocomplete(QLineEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.completer = QCompleter([])
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchContains)
        self.completer.setMaxVisibleItems(20)
        self.completer.setCompletionMode(QCompleter.PopupCompletion)
        self.setCompleter(self.completer)
        self.setMinimumHeight(35)

    def definir_itens(self, itens):
        self.completer.setModel(QStringListModel(itens))

class ClickableLabel(QLabel):
    clicked = pyqtSignal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

class DoubleClickLabel(QLabel):
    clicked = pyqtSignal()
    doubleClicked = pyqtSignal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)

# ========== JANELA PRINCIPAL ==========
class JanelaPrincipal(QMainWindow):
    # Definição dos temas
    TEMAS = {
        'claro': {
            'nome': 'Claro',
            'paleta': {
                'window': '#f0f0f0',
                'windowText': '#000000',
                'base': '#ffffff',
                'alternateBase': '#f5f5f5',
                'toolTipBase': '#ffffdc',
                'toolTipText': '#000000',
                'text': '#000000',
                'button': '#e0e0e0',
                'buttonText': '#000000',
                'brightText': '#ff0000',
                'highlight': '#3399ff',
                'highlightedText': '#ffffff',
            }
        },
        'escuro': {
            'nome': 'Escuro',
            'paleta': {
                'window': '#2b2b2b',
                'windowText': '#ffffff',
                'base': '#3c3c3c',
                'alternateBase': '#4a4a4a',
                'toolTipBase': '#ffffdc',
                'toolTipText': '#000000',
                'text': '#ffffff',
                'button': '#5a5a5a',
                'buttonText': '#ffffff',
                'brightText': '#ff0000',
                'highlight': '#1e90ff',
                'highlightedText': '#000000',
            }
        },
        'azul': {
            'nome': 'Azul',
            'paleta': {
                'window': '#e6f0fa',
                'windowText': '#003366',
                'base': '#ffffff',
                'alternateBase': '#f0f8ff',
                'toolTipBase': '#ffffdc',
                'toolTipText': '#000000',
                'text': '#003366',
                'button': '#b0c4de',
                'buttonText': '#003366',
                'brightText': '#ff0000',
                'highlight': '#4682b4',
                'highlightedText': '#ffffff',
            }
        },
        'amarelo': {
            'nome': 'Amarelo',
            'paleta': {
                'window': '#F4F6FF',
                'windowText': '#10375C',
                'base': '#FFFFFF',
                'alternateBase': '#F4F6FF',
                'toolTipBase': '#F3C623',
                'toolTipText': '#10375C',
                'text': '#10375C',
                'button': '#F3C623',
                'buttonText': '#10375C',
                'brightText': '#EB8317',
                'highlight': '#EB8317',
                'highlightedText': '#FFFFFF',
            }
        }
    }

    def __init__(self):
        super().__init__()

        font = QFont()
        font.setPointSize(10)
        QApplication.setFont(font)

        self.db = Database()
        if not self.db.connect():
            QMessageBox.critical(self, "Erro", "Não foi possível conectar ao banco!")
            sys.exit(1)

        if not self.db.criar_tabelas():
            QMessageBox.critical(self, "Erro", "Erro ao criar tabelas!")
            self.db.close()
            sys.exit(1)

        self.db.inicializar_dados()
        # Adicionar colunas de foto e apelidos se necessário
        self.db.verificar_e_adicionar_colunas()
        self.sistema = SistemaAlmoxarifado(self.db)

        # Inicializar atributos dinâmicos
        self.item_entrada_id = None
        self.item_saida_mult_id = None
        self.itens_saida_multipla = []
        self.nome_id = None
        self.historico_item_id = None

        self.setWindowTitle('Sistema de Almoxarifado - Versão 2.7.4')
        self.setGeometry(50, 50, 1800, 1000)
        self.center_window()

        self.criar_menu()
        self.criar_interface()
        self.carregar_dados_iniciais()

        self.status_bar = self.statusBar()
        self.status_label = QLabel('Sistema pronto')
        self.status_bar.addWidget(self.status_label)

        self.timer = QTimer()
        self.timer.timeout.connect(self.atualizar_status)
        self.timer.start(5000)

        self.settings = QSettings('Almoxarifado', 'Sistema')
        self.carregar_tema_salvo()

    def center_window(self):
        frame = self.frameGeometry()
        screen = QDesktopWidget().screenGeometry()
        center = screen.center()
        frame.moveCenter(center)
        self.move(frame.topLeft())

    def criar_menu(self):
        menubar = self.menuBar()

        arquivo_menu = menubar.addMenu('&Arquivo')
        novo_item = QAction('&Novo Item', self)
        novo_item.setShortcut('Ctrl+N')
        novo_item.triggered.connect(lambda: self.tabs.setCurrentIndex(0))
        arquivo_menu.addAction(novo_item)
        arquivo_menu.addSeparator()
        criar_backup = QAction('&Criar Backup', self)
        criar_backup.setShortcut('Ctrl+B')
        criar_backup.triggered.connect(self.criar_backup)
        arquivo_menu.addAction(criar_backup)
        arquivo_menu.addSeparator()
        sair = QAction('&Sair', self)
        sair.setShortcut('Ctrl+Q')
        sair.triggered.connect(self.close)
        arquivo_menu.addAction(sair)

        exportar_menu = menubar.addMenu('&Exportar')
        export_csv = QAction('Exportar para CSV', self)
        export_csv.triggered.connect(self.exportar_para_csv)
        exportar_menu.addAction(export_csv)
        export_html = QAction('Exportar para HTML', self)
        export_html.triggered.connect(self.exportar_para_html)
        exportar_menu.addAction(export_html)
        export_pdf = QAction('Exportar para PDF', self)
        export_pdf.triggered.connect(self.exportar_para_pdf)
        exportar_menu.addAction(export_pdf)

        ajuda_menu = menubar.addMenu('&Ajuda')
        sobre = QAction('&Sobre', self)
        sobre.triggered.connect(self.mostrar_sobre)
        ajuda_menu.addAction(sobre)
        config = QAction('&Configurações', self)
        config.triggered.connect(self.mostrar_configuracoes)
        ajuda_menu.addAction(config)

    def criar_interface(self):
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.criar_aba_cadastro()
        self.criar_aba_movimentacoes()
        self.criar_aba_nomes()
        self.criar_aba_inventario()
        self.criar_aba_previsao()
        self.criar_aba_backup()

    # ========== ABA CADASTRO ==========
    def criar_aba_cadastro(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(15)
        layout.setContentsMargins(15, 15, 15, 15)

        titulo = QLabel('📦 CADASTRO DE ITENS')
        titulo.setStyleSheet("font-size: 20px; font-weight: bold; color: #2c3e50; margin: 10px;")
        layout.addWidget(titulo)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        form_widget = QWidget()
        form_layout = QVBoxLayout(form_widget)
        form_layout.setSpacing(20)
        form_layout.setContentsMargins(20, 20, 20, 20)

        # Grupo 1 - Informações Básicas
        grupo1 = QGroupBox('INFORMAÇÕES BÁSICAS')
        grupo1.setStyleSheet("QGroupBox { font-weight: bold; margin-top: 10px; }")
        layout1 = QFormLayout()
        layout1.setSpacing(10)
        layout1.setContentsMargins(15, 15, 15, 15)

        self.codigo_input = QLineEdit()
        self.codigo_input.setPlaceholderText('Gerado automaticamente')
        self.codigo_input.setReadOnly(True)
        self.codigo_input.setMinimumHeight(35)
        layout1.addRow('🔖 Código do Item *', self.codigo_input)

        self.nome_oficial_input = QLineEdit()
        self.nome_oficial_input.setPlaceholderText('Nome oficial do item')
        self.nome_oficial_input.setMinimumHeight(35)
        layout1.addRow('🏷️ Nome Oficial *', self.nome_oficial_input)

        self.nome_fantasia_input = QLineEdit()
        self.nome_fantasia_input.setPlaceholderText('Como é conhecido na empresa')
        self.nome_fantasia_input.setMinimumHeight(35)
        layout1.addRow('👤 Nome Fantasia', self.nome_fantasia_input)

        # NOVO CAMPO: Apelidos
        self.apelidos_input = QLineEdit()
        self.apelidos_input.setPlaceholderText('Apelidos separados por vírgula (ex: caneta, bic)')
        self.apelidos_input.setMinimumHeight(35)
        layout1.addRow('🏷️ Apelidos', self.apelidos_input)

        self.categoria_combo = QComboBox()
        self.categoria_combo.addItems(['', 'Materiais', 'Ferramentas', 'Consumíveis', 'EPI', 'Embalagens', 'Tampas', 'Outros'])
        self.categoria_combo.setMinimumHeight(35)
        layout1.addRow('📁 Categoria:', self.categoria_combo)

        self.status_combo = QComboBox()
        self.status_combo.addItems(['Ativo', 'Em Compra', 'Inativo'])
        self.status_combo.setMinimumHeight(35)
        layout1.addRow('⚡ Status do Item *', self.status_combo)

        self.descricao_input = QTextEdit()
        self.descricao_input.setMaximumHeight(100)
        self.descricao_input.setPlaceholderText('Descreva características importantes...')
        layout1.addRow('📝 Descrição Detalhada:', self.descricao_input)

        grupo1.setLayout(layout1)
        form_layout.addWidget(grupo1)

        # Grupo 2 - Controle de Estoque
        grupo2 = QGroupBox('📊 CONTROLE DE ESTOQUE')
        grupo2.setStyleSheet("QGroupBox { font-weight: bold; margin-top: 10px; }")
        layout2 = QFormLayout()
        layout2.setSpacing(10)
        layout2.setContentsMargins(15, 15, 15, 15)

        self.estoque_minimo = QSpinBox()
        self.estoque_minimo.setRange(0, 10000)
        self.estoque_minimo.setValue(0)
        self.estoque_minimo.setMinimumHeight(35)
        layout2.addRow('⚠️ Estoque Mínimo *', self.estoque_minimo)

        self.estoque_atencao = QSpinBox()
        self.estoque_atencao.setRange(0, 10000)
        self.estoque_atencao.setSpecialValueText('Opcional')
        self.estoque_atencao.setMinimumHeight(35)
        layout2.addRow('🔔 Quantidade de Atenção', self.estoque_atencao)

        self.unidade_combo = QComboBox()
        self.unidade_combo.addItems(['Unidade (un)', 'Peça', 'Quilograma (kg)', 'Metro (m)', 'Litro (L)', 'Caixa', 'Pacote', 'Rolo'])
        self.unidade_combo.setMinimumHeight(35)
        layout2.addRow('⚖️ Unidade de Medida *', self.unidade_combo)

        grupo2.setLayout(layout2)
        form_layout.addWidget(grupo2)

        # Grupo 3 - Localização
        grupo3 = QGroupBox('📍 LOCALIZAÇÃO')
        grupo3.setStyleSheet("QGroupBox { font-weight: bold; margin-top: 10px; }")
        layout3 = QFormLayout()
        layout3.setSpacing(10)
        layout3.setContentsMargins(15, 15, 15, 15)

        self.local_principal = QLineEdit()
        self.local_principal.setPlaceholderText('Ex: A1, B2, Gaveta 3, Prateleira Superior')
        self.local_principal.setMinimumHeight(35)
        layout3.addRow('🏢 Local Principal *', self.local_principal)

        self.local_alternativo = QLineEdit()
        self.local_alternativo.setPlaceholderText('Opcional - segundo local')
        self.local_alternativo.setMinimumHeight(35)
        layout3.addRow('🗺️ Local Alternativo', self.local_alternativo)

        self.obs_localizacao = QTextEdit()
        self.obs_localizacao.setMaximumHeight(80)
        self.obs_localizacao.setPlaceholderText('Ex: Caixa vermelha, lado esquerdo...')
        layout3.addRow('📌 Observações da Localização', self.obs_localizacao)

        grupo3.setLayout(layout3)
        form_layout.addWidget(grupo3)

        # Grupo 4 - Controle de Validade
        grupo4 = QGroupBox('📅 CONTROLE DE VALIDADE')
        grupo4.setStyleSheet("QGroupBox { font-weight: bold; margin-top: 10px; }")
        layout4 = QHBoxLayout()
        layout4.setSpacing(15)
        layout4.setContentsMargins(15, 15, 15, 15)

        self.sem_validade = QRadioButton('🕒 Sem validade')
        self.sem_validade.setChecked(True)
        self.sem_validade.toggled.connect(lambda checked: self.data_validade.setEnabled(False))
        layout4.addWidget(self.sem_validade)

        self.com_validade = QRadioButton('📆 Com validade')
        self.com_validade.toggled.connect(lambda checked: self.data_validade.setEnabled(True))
        layout4.addWidget(self.com_validade)

        self.data_validade = QDateEdit()
        self.data_validade.setDate(QDate.currentDate().addYears(1))
        self.data_validade.setEnabled(False)
        self.data_validade.setMinimumHeight(35)
        layout4.addWidget(self.data_validade)

        layout4.addStretch()
        grupo4.setLayout(layout4)
        form_layout.addWidget(grupo4)

        # Grupo 5 - Foto do Item
        grupo5 = QGroupBox('📸 FOTO DO ITEM')
        grupo5.setStyleSheet("QGroupBox { font-weight: bold; margin-top: 10px; }")
        layout5 = QVBoxLayout()
        layout5.setSpacing(10)
        layout5.setContentsMargins(15, 15, 15, 15)

        self.foto_label = DoubleClickLabel()
        self.foto_label.setFixedSize(120, 120)
        self.foto_label.setStyleSheet("border: 2px dashed #aaa; border-radius: 5px; background-color: #f0f0f0;")
        self.foto_label.setAlignment(Qt.AlignCenter)
        self.foto_label.setText('🖼️\nClique para\nselecionar')
        self.foto_label.clicked.connect(self.selecionar_foto_item)
        self.foto_label.doubleClicked.connect(self.abrir_foto_ampliada_item)
        layout5.addWidget(self.foto_label, 0, Qt.AlignCenter)

        botoes_foto = QHBoxLayout()
        self.btn_remover_foto = QPushButton('🗑️ Remover Foto')
        self.btn_remover_foto.setMinimumHeight(35)
        self.btn_remover_foto.clicked.connect(self.remover_foto_item)
        self.btn_remover_foto.setEnabled(False)
        botoes_foto.addWidget(self.btn_remover_foto)
        botoes_foto.addStretch()
        layout5.addLayout(botoes_foto)

        grupo5.setLayout(layout5)
        form_layout.addWidget(grupo5)

        self.foto_item_bytes = None

        botoes_layout = QHBoxLayout()
        botoes_layout.setSpacing(15)

        limpar_btn = QPushButton('🧹 Limpar Formulário')
        limpar_btn.setMinimumHeight(40)
        limpar_btn.setStyleSheet("background-color: #95a5a6; color: white; padding: 10px; font-weight: bold;")
        limpar_btn.clicked.connect(self.limpar_cadastro)
        botoes_layout.addWidget(limpar_btn)

        salvar_btn = QPushButton('💾 Salvar Item')
        salvar_btn.setMinimumHeight(40)
        salvar_btn.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold; padding: 10px;")
        salvar_btn.clicked.connect(self.salvar_item)
        botoes_layout.addWidget(salvar_btn)

        form_layout.addLayout(botoes_layout)
        form_layout.addStretch()

        scroll.setWidget(form_widget)
        layout.addWidget(scroll)

        self.tabs.currentChanged.connect(self.atualizar_codigo_cadastro)

        self.tabs.addTab(widget, '📦 Cadastrar')

    def selecionar_foto_item(self):
        arquivo, _ = QFileDialog.getOpenFileName(self, "Selecionar Imagem", "", "Imagens (*.png *.jpg *.jpeg *.bmp *.gif)")
        if arquivo:
            dados_bytes = comprimir_imagem(arquivo)
            if dados_bytes:
                self.foto_item_bytes = dados_bytes
                pixmap = bytes_para_qpixmap(dados_bytes, 120, 120)
                self.foto_label.setPixmap(pixmap)
                self.btn_remover_foto.setEnabled(True)
            else:
                QMessageBox.warning(self, "Erro", "Não foi possível carregar a imagem.")

    def abrir_foto_ampliada_item(self):
        if self.foto_item_bytes:
            self.mostrar_foto_grande(self.foto_item_bytes)

    def remover_foto_item(self):
        self.foto_item_bytes = None
        self.foto_label.clear()
        self.foto_label.setText('🖼️\nClique para\nselecionar')
        self.btn_remover_foto.setEnabled(False)

    # ========== ABA MOVIMENTAÇÕES ==========
    def criar_aba_movimentacoes(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(15)
        layout.setContentsMargins(15, 15, 15, 15)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(20)
        scroll_layout.setContentsMargins(10, 10, 10, 10)

        self.mov_tabs = QTabWidget()
        entrada_widget = QWidget()
        self.criar_form_entrada(entrada_widget)
        self.mov_tabs.addTab(entrada_widget, '⬇️ Entrada')
        saida_multipla_widget = QWidget()
        self.criar_form_saida_multipla(saida_multipla_widget)
        self.mov_tabs.addTab(saida_multipla_widget, '📦 Saída Múltipla')
        historico_widget = QWidget()
        self.criar_historico(historico_widget)  # método modificado
        self.mov_tabs.addTab(historico_widget, '📋 Histórico')

        scroll_layout.addWidget(self.mov_tabs)
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)
        self.tabs.addTab(widget, '🔄 Movimentações')

    def criar_form_entrada(self, parent):
        layout = QVBoxLayout(parent)
        layout.setSpacing(15)
        layout.setContentsMargins(15, 15, 15, 15)

        titulo = QLabel('ENTRADA DE ITENS')
        titulo.setStyleSheet("font-size: 16px; font-weight: bold; color: #27ae60; margin: 10px;")
        layout.addWidget(titulo)

        form_widget = QWidget()
        form_layout = QFormLayout(form_widget)
        form_layout.setSpacing(10)
        form_layout.setContentsMargins(15, 15, 15, 15)

        self.entrada_busca = CampoAutocomplete()
        self.entrada_busca.setPlaceholderText('Digite código ou nome do item...')
        self.entrada_busca.textChanged.connect(self.atualizar_info_entrada_digito)
        self.entrada_busca.returnPressed.connect(lambda: self.processar_selecao_item(self.entrada_busca, self.entrada_info, 'item_entrada_id'))
        self.entrada_busca.completer.activated.connect(lambda: self.processar_selecao_item(self.entrada_busca, self.entrada_info, 'item_entrada_id'))

        btn_ver_todos = QPushButton('🔍 Ver Todos')
        btn_ver_todos.setMinimumHeight(35)
        btn_ver_todos.clicked.connect(self.mostrar_todos_itens_entrada)

        busca_layout = QHBoxLayout()
        busca_layout.setSpacing(10)
        busca_layout.addWidget(self.entrada_busca)
        busca_layout.addWidget(btn_ver_todos)
        form_layout.addRow('Item:', busca_layout)

        self.entrada_info = QLabel('Selecione um item')
        self.entrada_info.setStyleSheet("background-color: #f8f9fa; padding: 10px; border: 1px solid #ddd; border-radius: 5px;")
        self.entrada_info.setWordWrap(True)
        self.entrada_info.setMinimumHeight(60)
        form_layout.addRow('Informações:', self.entrada_info)

        self.entrada_qtd = QSpinBox()
        self.entrada_qtd.setRange(1, 10000)
        self.entrada_qtd.setValue(1)
        self.entrada_qtd.setMinimumHeight(35)
        form_layout.addRow('📦 Quantidade:', self.entrada_qtd)

        # Responsável com foto (tamanho padronizado 50x50)
        resp_widget = QWidget()
        resp_layout = QHBoxLayout(resp_widget)
        resp_layout.setContentsMargins(0, 0, 0, 0)

        self.entrada_responsavel = CampoAutocomplete()
        self.entrada_responsavel.setPlaceholderText('Nome do responsável')
        self.entrada_responsavel.setMinimumHeight(35)
        resp_layout.addWidget(self.entrada_responsavel, 1)

        self.responsavel_foto_label_entrada = DoubleClickLabel()
        self.responsavel_foto_label_entrada.setFixedSize(50, 50)
        self.responsavel_foto_label_entrada.setStyleSheet("border: 1px solid #ccc; border-radius: 3px; background-color: #f9f9f9;")
        self.responsavel_foto_label_entrada.setAlignment(Qt.AlignCenter)
        self.responsavel_foto_label_entrada.setText('📷')
        self.responsavel_foto_label_entrada.doubleClicked.connect(lambda: self.abrir_foto_responsavel_entrada())
        resp_layout.addWidget(self.responsavel_foto_label_entrada)

        form_layout.addRow('👤 Responsável:', resp_widget)

        # Conectar sinais para atualização dinâmica da foto
        self.entrada_responsavel.textChanged.connect(lambda: self.atualizar_foto_responsavel_dinamico(self.entrada_responsavel.text().strip(), self.responsavel_foto_label_entrada, 'responsavel_foto_atual_entrada'))
        self.entrada_responsavel.completer.activated.connect(lambda: self.atualizar_foto_responsavel_apos_selecao(self.entrada_responsavel.text().strip(), self.responsavel_foto_label_entrada, 'responsavel_foto_atual_entrada'))
        self.entrada_responsavel.returnPressed.connect(lambda: self.atualizar_foto_responsavel_apos_selecao(self.entrada_responsavel.text().strip(), self.responsavel_foto_label_entrada, 'responsavel_foto_atual_entrada'))

        self.entrada_fornecedor = QLineEdit()
        self.entrada_fornecedor.setPlaceholderText('Opcional')
        self.entrada_fornecedor.setMinimumHeight(35)
        form_layout.addRow('🚚 Fornecedor:', self.entrada_fornecedor)

        self.entrada_nota = QLineEdit()
        self.entrada_nota.setPlaceholderText('Opcional')
        self.entrada_nota.setMinimumHeight(35)
        form_layout.addRow('🧾 Nota Fiscal:', self.entrada_nota)

        self.entrada_obs = QTextEdit()
        self.entrada_obs.setMaximumHeight(80)
        self.entrada_obs.setPlaceholderText('Observações...')
        form_layout.addRow('📝 Observações:', self.entrada_obs)

        botoes_layout = QHBoxLayout()
        botoes_layout.setSpacing(15)

        limpar_btn = QPushButton('🧹 Limpar')
        limpar_btn.setMinimumHeight(40)
        limpar_btn.clicked.connect(self.limpar_entrada)
        botoes_layout.addWidget(limpar_btn)

        salvar_btn = QPushButton('✅ Registrar Entrada')
        salvar_btn.setMinimumHeight(40)
        salvar_btn.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold; padding: 10px;")
        salvar_btn.clicked.connect(self.registrar_entrada)
        botoes_layout.addWidget(salvar_btn)

        form_layout.addRow('', botoes_layout)
        layout.addWidget(form_widget)
        layout.addStretch()

    def criar_form_saida_multipla(self, parent):
        layout = QVBoxLayout(parent)
        layout.setSpacing(15)
        layout.setContentsMargins(15, 15, 15, 15)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea { border: none; }
            QScrollBar:vertical { background: #f0f0f0; width: 12px; border-radius: 6px; }
            QScrollBar::handle:vertical { background: #c0c0c0; border-radius: 6px; min-height: 30px; }
        """)

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setSpacing(20)
        container_layout.setContentsMargins(20, 20, 20, 20)

        # Seção 1: Adicionar Item
        grupo_add = QGroupBox('➕ ADICIONAR ITEM À SAÍDA')
        grupo_add.setMinimumHeight(300)
        grupo_add.setStyleSheet("""
            QGroupBox { font-weight: bold; font-size: 14px; padding-top: 15px; border: 2px solid #3498db; border-radius: 8px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 10px 0 10px; color: #3498db; }
        """)
        add_layout = QVBoxLayout(grupo_add)
        add_layout.setSpacing(15)
        add_layout.setContentsMargins(15, 20, 15, 15)

        busca_layout = QHBoxLayout()
        busca_layout.setSpacing(10)
        self.saida_mult_busca = CampoAutocomplete()
        self.saida_mult_busca.setPlaceholderText('Digite código ou nome do item...')
        self.saida_mult_busca.setMinimumHeight(40)
        self.saida_mult_busca.textChanged.connect(self.atualizar_info_saida_digito)
        self.saida_mult_busca.returnPressed.connect(self.on_saida_mult_busca_confirmado)
        self.saida_mult_busca.completer.activated.connect(self.on_saida_mult_busca_confirmado)
        btn_ver_todos = QPushButton('🔍 Ver Todos')
        btn_ver_todos.setMinimumHeight(40)
        btn_ver_todos.setMinimumWidth(120)
        btn_ver_todos.clicked.connect(self.mostrar_todos_itens_multipla)
        busca_layout.addWidget(self.saida_mult_busca)
        busca_layout.addWidget(btn_ver_todos)
        add_layout.addLayout(busca_layout)

        # Área de informação do item com foto (80x80)
        info_item_widget = QWidget()
        info_item_layout = QHBoxLayout(info_item_widget)
        info_item_layout.setContentsMargins(0, 0, 0, 0)

        self.item_foto_label = DoubleClickLabel()
        self.item_foto_label.setFixedSize(80, 80)
        self.item_foto_label.setStyleSheet("border: 1px solid #ccc; border-radius: 3px; background-color: #f9f9f9;")
        self.item_foto_label.setAlignment(Qt.AlignCenter)
        self.item_foto_label.setText('📷')
        self.item_foto_label.doubleClicked.connect(lambda: self.abrir_foto_item_atual())
        info_item_layout.addWidget(self.item_foto_label)

        self.saida_mult_info = QLabel('ℹ️ Nenhum item selecionado. Use a busca acima para encontrar um item.')
        self.saida_mult_info.setStyleSheet("background-color: #f8f9fa; padding: 15px; border: 1px solid #dee2e6; border-radius: 6px; color: #6c757d; font-size: 13px;")
        self.saida_mult_info.setWordWrap(True)
        self.saida_mult_info.setMinimumHeight(90)
        info_item_layout.addWidget(self.saida_mult_info, 1)

        add_layout.addWidget(info_item_widget)

        detalhes_layout = QHBoxLayout()
        detalhes_layout.setSpacing(20)

        qtd_container = QWidget()
        qtd_layout = QVBoxLayout(qtd_container)
        qtd_label = QLabel('📦 QUANTIDADE')
        qtd_label.setStyleSheet("font-weight: bold; color: #2c3e50; margin-bottom: 5px;")
        qtd_layout.addWidget(qtd_label)
        self.saida_mult_qtd = QSpinBox()
        self.saida_mult_qtd.setRange(1, 9999)
        self.saida_mult_qtd.setValue(1)
        self.saida_mult_qtd.setMinimumHeight(40)
        qtd_layout.addWidget(self.saida_mult_qtd)
        detalhes_layout.addWidget(qtd_container, 1)

        obs_container = QWidget()
        obs_layout = QVBoxLayout(obs_container)
        obs_label = QLabel('📝 OBSERVAÇÕES DO ITEM')
        obs_label.setStyleSheet("font-weight: bold; color: #2c3e50; margin-bottom: 5px;")
        obs_layout.addWidget(obs_label)
        self.saida_mult_obs_item = QLineEdit()
        self.saida_mult_obs_item.setPlaceholderText('Ex: Item com defeito, para teste, urgente...')
        self.saida_mult_obs_item.setMinimumHeight(40)
        obs_layout.addWidget(self.saida_mult_obs_item)
        detalhes_layout.addWidget(obs_container, 2)
        add_layout.addLayout(detalhes_layout)

        btn_adicionar = QPushButton('➕ ADICIONAR À LISTA')
        btn_adicionar.setMinimumHeight(45)
        btn_adicionar.clicked.connect(self.adicionar_item_saida_multipla)
        btn_adicionar.setStyleSheet("background-color: #3498db; color: white; border: none; border-radius: 6px; font-weight: bold; font-size: 13px;")
        add_layout.addWidget(btn_adicionar, 0, Qt.AlignCenter)
        container_layout.addWidget(grupo_add)

        # Seção 2: Lista de Itens
        grupo_lista = QGroupBox('📋 LISTA DE ITENS PARA SAÍDA')
        grupo_lista.setStyleSheet("""
            QGroupBox { font-weight: bold; font-size: 14px; padding-top: 15px; border: 2px solid #27ae60; border-radius: 8px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 10px 0 10px; color: #27ae60; }
        """)
        lista_layout = QVBoxLayout(grupo_lista)
        lista_layout.setSpacing(15)
        lista_layout.setContentsMargins(15, 20, 15, 15)

        contador_widget = QWidget()
        contador_layout = QHBoxLayout(contador_widget)
        contador_label = QLabel('Quantidade de itens na lista:')
        contador_label.setStyleSheet("font-weight: bold; color: #27ae60;")
        contador_layout.addWidget(contador_label)
        self.contador_itens = QLabel('0')
        self.contador_itens.setStyleSheet("background-color: #27ae60; color: white; padding: 5px 15px; border-radius: 12px; font-weight: bold; font-size: 13px;")
        contador_layout.addWidget(self.contador_itens)
        contador_layout.addStretch()
        lista_layout.addWidget(contador_widget)

        self.tabela_itens_saida = QTableWidget()
        self.tabela_itens_saida.setColumnCount(6)
        self.tabela_itens_saida.setHorizontalHeaderLabels(['CÓDIGO', 'ITEM', 'QUANTIDADE', 'UNIDADE', 'OBSERVAÇÕES', 'AÇÕES'])
        self.tabela_itens_saida.setMinimumHeight(250)
        self.tabela_itens_saida.setColumnWidth(0, 100)
        self.tabela_itens_saida.setColumnWidth(1, 250)
        self.tabela_itens_saida.setColumnWidth(2, 100)
        self.tabela_itens_saida.setColumnWidth(3, 80)
        self.tabela_itens_saida.setColumnWidth(4, 200)
        self.tabela_itens_saida.horizontalHeader().setStretchLastSection(True)
        self.tabela_itens_saida.verticalHeader().setVisible(False)
        self.tabela_itens_saida.verticalHeader().setDefaultSectionSize(30)
        self.tabela_itens_saida.setAlternatingRowColors(True)
        lista_layout.addWidget(self.tabela_itens_saida)

        botoes_lista = QWidget()
        botoes_lista_layout = QHBoxLayout(botoes_lista)
        botoes_lista_layout.setSpacing(15)
        btn_remover_selecionado = QPushButton('🗑️ REMOVER SELECIONADO')
        btn_remover_selecionado.setMinimumHeight(40)
        btn_remover_selecionado.clicked.connect(self.remover_item_saida_multipla)
        btn_remover_selecionado.setStyleSheet("background-color: #e74c3c; color: white; border: none; border-radius: 6px; font-weight: bold; font-size: 12px;")
        botoes_lista_layout.addWidget(btn_remover_selecionado)
        btn_limpar_lista = QPushButton('🧹 LIMPAR LISTA')
        btn_limpar_lista.setMinimumHeight(40)
        btn_limpar_lista.clicked.connect(self.limpar_lista_saida_multipla)
        btn_limpar_lista.setStyleSheet("background-color: #f39c12; color: white; border: none; border-radius: 6px; font-weight: bold; font-size: 12px;")
        botoes_lista_layout.addWidget(btn_limpar_lista)
        botoes_lista_layout.addStretch()
        lista_layout.addWidget(botoes_lista)
        container_layout.addWidget(grupo_lista)

        # Seção 3: Informações da Saída
        grupo_info = QGroupBox('📝 INFORMAÇÕES DA SAÍDA')
        grupo_info.setStyleSheet("""
            QGroupBox { font-weight: bold; font-size: 14px; padding-top: 15px; border: 2px solid #9b59b6; border-radius: 8px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 10px 0 10px; color: #9b59b6; }
        """)
        info_form_layout = QVBoxLayout(grupo_info)
        info_form_layout.setSpacing(15)
        info_form_layout.setContentsMargins(15, 20, 15, 15)

        # Responsável com foto (padronizado 50x50)
        resp_container = QWidget()
        resp_vbox = QVBoxLayout(resp_container)
        resp_label = QLabel('👤 RESPONSÁVEL *')
        resp_label.setStyleSheet("font-weight: bold; color: #2c3e50; margin-bottom: 5px;")
        resp_vbox.addWidget(resp_label)

        resp_hbox = QHBoxLayout()
        self.saida_mult_responsavel = CampoAutocomplete()
        self.saida_mult_responsavel.setPlaceholderText('Nome completo do responsável')
        self.saida_mult_responsavel.setMinimumHeight(40)
        resp_hbox.addWidget(self.saida_mult_responsavel, 1)

        self.responsavel_foto_label_saida = DoubleClickLabel()
        self.responsavel_foto_label_saida.setFixedSize(50, 50)
        self.responsavel_foto_label_saida.setStyleSheet("border: 1px solid #ccc; border-radius: 3px; background-color: #f9f9f9;")
        self.responsavel_foto_label_saida.setAlignment(Qt.AlignCenter)
        self.responsavel_foto_label_saida.setText('📷')
        self.responsavel_foto_label_saida.doubleClicked.connect(lambda: self.abrir_foto_responsavel_saida())
        resp_hbox.addWidget(self.responsavel_foto_label_saida)

        resp_vbox.addLayout(resp_hbox)
        info_form_layout.addWidget(resp_container)

        # Conectar sinais do responsável para atualização dinâmica da foto
        self.saida_mult_responsavel.textChanged.connect(lambda: self.atualizar_foto_responsavel_dinamico(self.saida_mult_responsavel.text().strip(), self.responsavel_foto_label_saida, 'responsavel_foto_atual_saida'))
        self.saida_mult_responsavel.completer.activated.connect(lambda: self.atualizar_foto_responsavel_apos_selecao(self.saida_mult_responsavel.text().strip(), self.responsavel_foto_label_saida, 'responsavel_foto_atual_saida'))
        self.saida_mult_responsavel.returnPressed.connect(lambda: self.atualizar_foto_responsavel_apos_selecao(self.saida_mult_responsavel.text().strip(), self.responsavel_foto_label_saida, 'responsavel_foto_atual_saida'))

        # Colaborador com foto (padronizado 50x50)
        colab_container = QWidget()
        colab_vbox = QVBoxLayout(colab_container)
        colab_label = QLabel('👥 COLABORADOR *')
        colab_label.setStyleSheet("font-weight: bold; color: #2c3e50; margin-bottom: 5px;")
        colab_vbox.addWidget(colab_label)

        colab_hbox = QHBoxLayout()
        self.saida_mult_colaborador = CampoAutocomplete()
        self.saida_mult_colaborador.setPlaceholderText('Nome do colaborador que receberá')
        self.saida_mult_colaborador.setMinimumHeight(40)
        colab_hbox.addWidget(self.saida_mult_colaborador, 1)

        self.colaborador_foto_label = DoubleClickLabel()
        self.colaborador_foto_label.setFixedSize(50, 50)  # Padronizado 50x50
        self.colaborador_foto_label.setStyleSheet("border: 1px solid #ccc; border-radius: 3px; background-color: #f9f9f9;")
        self.colaborador_foto_label.setAlignment(Qt.AlignCenter)
        self.colaborador_foto_label.setText('📷')
        self.colaborador_foto_label.doubleClicked.connect(lambda: self.abrir_foto_colaborador_atual())
        colab_hbox.addWidget(self.colaborador_foto_label)

        colab_vbox.addLayout(colab_hbox)
        info_form_layout.addWidget(colab_container)

        # Conectar sinais do colaborador
        self.saida_mult_colaborador.completer.activated.connect(self.on_colaborador_selected)
        self.saida_mult_colaborador.returnPressed.connect(self.on_colaborador_selected)
        self.saida_mult_colaborador.textChanged.connect(self.atualizar_foto_colaborador_dinamico)

        # Setor
        setor_container = QWidget()
        setor_vbox = QVBoxLayout(setor_container)
        setor_label = QLabel('🏢 SETOR / DEPARTAMENTO')
        setor_label.setStyleSheet("font-weight: bold; color: #2c3e50; margin-bottom: 5px;")
        setor_vbox.addWidget(setor_label)
        self.saida_mult_setor = QLineEdit()
        self.saida_mult_setor.setPlaceholderText('Ex: TI, Manutenção, Almoxarifado')
        self.saida_mult_setor.setMinimumHeight(40)
        setor_vbox.addWidget(self.saida_mult_setor)
        info_form_layout.addWidget(setor_container)

        # Observações gerais
        obs_geral_label = QLabel('📋 OBSERVAÇÕES GERAIS')
        obs_geral_label.setStyleSheet("font-weight: bold; color: #2c3e50;")
        info_form_layout.addWidget(obs_geral_label)
        self.saida_mult_obs_geral = QTextEdit()
        self.saida_mult_obs_geral.setPlaceholderText('Observações gerais sobre esta saída...')
        self.saida_mult_obs_geral.setMinimumHeight(100)
        info_form_layout.addWidget(self.saida_mult_obs_geral)

        container_layout.addWidget(grupo_info)

        botoes_finais = QWidget()
        botoes_layout = QHBoxLayout(botoes_finais)
        botoes_layout.setSpacing(20)
        btn_limpar_tudo = QPushButton('🔄 LIMPAR TUDO')
        btn_limpar_tudo.setMinimumHeight(45)
        btn_limpar_tudo.setMinimumWidth(150)
        btn_limpar_tudo.clicked.connect(self.limpar_saida_multipla)
        btn_limpar_tudo.setStyleSheet("background-color: #95a5a6; color: white; border: none; border-radius: 6px; font-weight: bold;")
        botoes_layout.addWidget(btn_limpar_tudo)
        botoes_layout.addStretch()
        btn_registrar = QPushButton('✅ REGISTRAR SAÍDA MÚLTIPLA')
        btn_registrar.setMinimumHeight(50)
        btn_registrar.setMinimumWidth(250)
        btn_registrar.clicked.connect(self.registrar_saida_multipla)
        btn_registrar.setStyleSheet("background-color: #e67e22; color: white; border: none; border-radius: 8px; font-weight: bold; font-size: 14px;")
        botoes_layout.addWidget(btn_registrar)
        botoes_layout.addStretch()
        container_layout.addWidget(botoes_finais)
        container_layout.addStretch()

        scroll.setWidget(container)
        layout.addWidget(scroll)

    # ========== MÉTODO criar_historico MODIFICADO ==========
    def criar_historico(self, parent):
        layout = QVBoxLayout(parent)
        layout.setSpacing(15)
        layout.setContentsMargins(15, 15, 15, 15)

        titulo = QLabel('HISTÓRICO DE MOVIMENTAÇÕES')
        titulo.setStyleSheet("font-size: 16px; font-weight: bold; margin: 10px;")
        layout.addWidget(titulo)

        # Filtros: tipo e período (linha 1)
        filtros_widget1 = QWidget()
        filtros_layout1 = QHBoxLayout(filtros_widget1)
        filtros_layout1.setSpacing(10)
        filtros_layout1.addWidget(QLabel('Tipo:'))
        self.historico_tipo = QComboBox()
        self.historico_tipo.addItems(['Todos', 'Entrada', 'Saída'])
        self.historico_tipo.setMinimumHeight(35)
        filtros_layout1.addWidget(self.historico_tipo)
        filtros_layout1.addWidget(QLabel('De:'))
        self.historico_de = QDateEdit()
        self.historico_de.setDate(QDate.currentDate().addDays(-30))
        self.historico_de.setMinimumHeight(35)
        filtros_layout1.addWidget(self.historico_de)
        filtros_layout1.addWidget(QLabel('Até:'))
        self.historico_ate = QDateEdit()
        self.historico_ate.setDate(QDate.currentDate())
        self.historico_ate.setMinimumHeight(35)
        filtros_layout1.addWidget(self.historico_ate)
        filtrar_btn = QPushButton('🔍 Filtrar')
        filtrar_btn.setMinimumHeight(35)
        filtrar_btn.clicked.connect(self.carregar_historico)
        filtros_layout1.addWidget(filtrar_btn)
        filtros_layout1.addStretch()
        layout.addWidget(filtros_widget1)

        # Filtro por item (linha 2)
        filtros_widget2 = QWidget()
        filtros_layout2 = QHBoxLayout(filtros_widget2)
        filtros_layout2.setSpacing(10)
        filtros_layout2.addWidget(QLabel('Item:'))
        self.historico_item_busca = CampoAutocomplete()
        self.historico_item_busca.setPlaceholderText('Digite código ou nome do item...')
        self.historico_item_busca.setMinimumHeight(35)
        self.historico_item_busca.textChanged.connect(self.atualizar_info_historico_digito)
        self.historico_item_busca.returnPressed.connect(self.on_historico_item_selecionado)
        self.historico_item_busca.completer.activated.connect(self.on_historico_item_selecionado)
        filtros_layout2.addWidget(self.historico_item_busca, 1)

        btn_limpar_item = QPushButton('🧹 Limpar Item')
        btn_limpar_item.setMinimumHeight(35)
        btn_limpar_item.clicked.connect(self.limpar_filtro_item_historico)
        filtros_layout2.addWidget(btn_limpar_item)
        filtros_layout2.addStretch()
        layout.addWidget(filtros_widget2)

        self.historico_item_id = None  # armazena o ID do item selecionado

        # Tabela de histórico
        self.historico_table = QTableWidget()
        self.historico_table.setColumnCount(10)
        self.historico_table.setHorizontalHeaderLabels([
            'Data', 'Item', 'Código', 'Tipo', 'Quantidade',
            'Resp.', 'Foto Resp.', 'Colab.', 'Foto Colab.', 'Observações'
        ])
        self.historico_table.horizontalHeader().setStretchLastSection(True)
        self.historico_table.verticalHeader().setDefaultSectionSize(40)
        self.historico_table.setColumnWidth(6, 50)
        self.historico_table.setColumnWidth(8, 50)
        layout.addWidget(self.historico_table)

        self.carregar_historico()

    # ========== ABA NOMES ==========
    def criar_aba_nomes(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(15)
        layout.setContentsMargins(15, 15, 15, 15)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(20)
        scroll_layout.setContentsMargins(10, 10, 10, 10)

        titulo = QLabel('👥 CADASTRO DE NOMES')
        titulo.setStyleSheet("font-size: 18px; font-weight: bold; color: #2c3e50; margin: 10px;")
        scroll_layout.addWidget(titulo)

        form_widget = QWidget()
        form_layout = QFormLayout(form_widget)
        form_layout.setSpacing(10)
        form_layout.setContentsMargins(15, 15, 15, 15)

        self.nome_id = None
        self.nome_input = QLineEdit()
        self.nome_input.setPlaceholderText('Nome completo')
        self.nome_input.setMinimumHeight(35)
        form_layout.addRow('👤 Nome *:', self.nome_input)

        self.nome_tipo = QComboBox()
        self.nome_tipo.addItems(['responsavel', 'colaborador', 'fornecedor'])
        self.nome_tipo.setMinimumHeight(35)
        form_layout.addRow('🏷️ Tipo *:', self.nome_tipo)

        self.nome_setor_combo = QComboBox()
        self.nome_setor_combo.addItems(['', 'Produção', 'Acabamento', 'Expedição', 'Estoque', 'Administração'])
        self.nome_setor_combo.setEditable(True)
        self.nome_setor_combo.setMinimumHeight(35)
        form_layout.addRow('🏢 Setor:', self.nome_setor_combo)

        self.nome_email = QLineEdit()
        self.nome_email.setPlaceholderText('Opcional')
        self.nome_email.setMinimumHeight(35)
        form_layout.addRow('📧 Email:', self.nome_email)

        self.nome_telefone = QLineEdit()
        self.nome_telefone.setPlaceholderText('Opcional')
        self.nome_telefone.setMinimumHeight(35)
        form_layout.addRow('📞 Telefone:', self.nome_telefone)

        self.nome_observacoes = QTextEdit()
        self.nome_observacoes.setMaximumHeight(80)
        self.nome_observacoes.setPlaceholderText('Observações...')
        form_layout.addRow('📝 Observações:', self.nome_observacoes)

        status_layout = QHBoxLayout()
        status_layout.setSpacing(15)
        self.nome_status_ativo = QRadioButton('✅ Ativo')
        self.nome_status_ativo.setChecked(True)
        self.nome_status_inativo = QRadioButton('❌ Inativo')
        status_layout.addWidget(self.nome_status_ativo)
        status_layout.addWidget(self.nome_status_inativo)
        status_layout.addStretch()
        form_layout.addRow('⚡ Status:', status_layout)

        # Grupo de foto para nomes (120x120 no cadastro)
        grupo_foto = QGroupBox('📸 FOTO')
        grupo_foto.setStyleSheet("QGroupBox { font-weight: bold; }")
        foto_layout = QVBoxLayout(grupo_foto)
        self.foto_nome_label = DoubleClickLabel()
        self.foto_nome_label.setFixedSize(120, 120)
        self.foto_nome_label.setStyleSheet("border: 2px dashed #aaa; border-radius: 5px; background-color: #f0f0f0;")
        self.foto_nome_label.setAlignment(Qt.AlignCenter)
        self.foto_nome_label.setText('🖼️\nClique para\nselecionar')
        self.foto_nome_label.clicked.connect(self.selecionar_foto_nome)
        self.foto_nome_label.doubleClicked.connect(self.abrir_foto_ampliada_nome)
        foto_layout.addWidget(self.foto_nome_label, 0, Qt.AlignCenter)

        botoes_foto = QHBoxLayout()
        self.btn_remover_foto_nome = QPushButton('🗑️ Remover Foto')
        self.btn_remover_foto_nome.setMinimumHeight(35)
        self.btn_remover_foto_nome.clicked.connect(self.remover_foto_nome)
        self.btn_remover_foto_nome.setEnabled(False)
        botoes_foto.addWidget(self.btn_remover_foto_nome)
        botoes_foto.addStretch()
        foto_layout.addLayout(botoes_foto)
        form_layout.addRow('', grupo_foto)

        self.foto_nome_bytes = None

        botoes_layout = QHBoxLayout()
        botoes_layout.setSpacing(15)

        limpar_btn = QPushButton('🧹 Limpar')
        limpar_btn.setMinimumHeight(40)
        limpar_btn.clicked.connect(self.limpar_nome)
        botoes_layout.addWidget(limpar_btn)

        self.nome_btn_salvar = QPushButton('💾 Salvar Nome')
        self.nome_btn_salvar.setMinimumHeight(40)
        self.nome_btn_salvar.setStyleSheet("background-color: #3498db; color: white; font-weight: bold; padding: 10px;")
        self.nome_btn_salvar.clicked.connect(self.salvar_nome)
        botoes_layout.addWidget(self.nome_btn_salvar)

        form_layout.addRow('', botoes_layout)
        scroll_layout.addWidget(form_widget)

        lista_titulo = QLabel('NOMES CADASTRADOS')
        lista_titulo.setStyleSheet("font-size: 16px; font-weight: bold; margin-top: 20px;")
        scroll_layout.addWidget(lista_titulo)

        filtro_widget = QWidget()
        filtro_layout = QHBoxLayout(filtro_widget)
        filtro_layout.setSpacing(10)
        filtro_layout.addWidget(QLabel('Filtrar:'))
        self.nome_filtro = QComboBox()
        self.nome_filtro.addItems(['Todos', 'Ativos', 'Inativos', 'Responsável', 'Colaborador', 'Setor', 'Fornecedor'])
        self.nome_filtro.setMinimumHeight(35)
        self.nome_filtro.currentIndexChanged.connect(self.carregar_lista_nomes)
        filtro_layout.addWidget(self.nome_filtro)
        filtro_layout.addStretch()
        scroll_layout.addWidget(filtro_widget)

        self.nomes_table = QTableWidget()
        self.nomes_table.setColumnCount(8)
        self.nomes_table.setHorizontalHeaderLabels(['Foto', 'Nome', 'Tipo', 'Setor', 'Email', 'Telefone', 'Status', 'Ações'])
        self.nomes_table.horizontalHeader().setStretchLastSection(True)
        self.nomes_table.verticalHeader().setDefaultSectionSize(40)
        self.nomes_table.setSelectionBehavior(QTableWidget.SelectRows)
        scroll_layout.addWidget(self.nomes_table)

        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)
        self.tabs.addTab(widget, '👥 Nomes')

    def selecionar_foto_nome(self):
        arquivo, _ = QFileDialog.getOpenFileName(self, "Selecionar Imagem", "", "Imagens (*.png *.jpg *.jpeg *.bmp *.gif)")
        if arquivo:
            dados_bytes = comprimir_imagem(arquivo)
            if dados_bytes:
                self.foto_nome_bytes = dados_bytes
                pixmap = bytes_para_qpixmap(dados_bytes, 120, 120)
                self.foto_nome_label.setPixmap(pixmap)
                self.btn_remover_foto_nome.setEnabled(True)
            else:
                QMessageBox.warning(self, "Erro", "Não foi possível carregar a imagem.")

    def abrir_foto_ampliada_nome(self):
        if self.foto_nome_bytes:
            self.mostrar_foto_grande(self.foto_nome_bytes)

    def remover_foto_nome(self):
        self.foto_nome_bytes = None
        self.foto_nome_label.clear()
        self.foto_nome_label.setText('🖼️\nClique para\nselecionar')
        self.btn_remover_foto_nome.setEnabled(False)

    # ========== ABA INVENTÁRIO ==========
    def criar_aba_inventario(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(15)
        layout.setContentsMargins(15, 15, 15, 15)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(20)
        scroll_layout.setContentsMargins(10, 10, 10, 10)

        titulo = QLabel('📋 INVENTÁRIO COMPLETO')
        titulo.setStyleSheet("font-size: 18px; font-weight: bold; color: #2c3e50; margin: 10px;")
        scroll_layout.addWidget(titulo)

        filtros_widget = QWidget()
        filtros_layout = QHBoxLayout(filtros_widget)
        filtros_layout.setSpacing(10)
        self.inventario_busca = QLineEdit()
        self.inventario_busca.setPlaceholderText('Buscar por nome, código ou local...')
        self.inventario_busca.setMinimumHeight(35)
        self.inventario_busca.textChanged.connect(self.filtrar_inventario)
        filtros_layout.addWidget(self.inventario_busca)

        self.inventario_filtro = QComboBox()
        self.inventario_filtro.addItems(['Todos', 'Ativos', 'Em Compra', 'Inativos', 'Críticos', 'Atenção', 'Validade'])
        self.inventario_filtro.setMinimumHeight(35)
        self.inventario_filtro.currentIndexChanged.connect(self.filtrar_inventario)
        filtros_layout.addWidget(self.inventario_filtro)

        limpar_btn = QPushButton('🧹 Limpar')
        limpar_btn.setMinimumHeight(35)
        limpar_btn.clicked.connect(self.limpar_busca_inventario)
        filtros_layout.addWidget(limpar_btn)

        exportar_btn = QPushButton('📁 Exportar')
        exportar_btn.setMinimumHeight(35)
        exportar_btn.clicked.connect(self.exportar_inventario_dialog)
        filtros_layout.addWidget(exportar_btn)

        filtros_layout.addStretch()
        scroll_layout.addWidget(filtros_widget)

        cartoes_widget = QWidget()
        cartoes_layout = QHBoxLayout(cartoes_widget)
        cartoes_layout.setSpacing(15)

        self.cartao_total = QFrame()
        self.cartao_total.setStyleSheet("background-color: #3498db; border-radius: 8px; padding: 15px;")
        cartao_total_layout = QVBoxLayout(self.cartao_total)
        cartao_total_layout.addWidget(QLabel('📦 TOTAL'))
        self.total_label = QLabel('0')
        self.total_label.setStyleSheet("font-size: 28px; font-weight: bold; color: white;")
        cartao_total_layout.addWidget(self.total_label)
        cartoes_layout.addWidget(self.cartao_total)

        self.cartao_ativos = QFrame()
        self.cartao_ativos.setStyleSheet("background-color: #2ecc71; border-radius: 8px; padding: 15px;")
        cartao_ativos_layout = QVBoxLayout(self.cartao_ativos)
        cartao_ativos_layout.addWidget(QLabel('✅ ATIVOS'))
        self.ativos_label = QLabel('0')
        self.ativos_label.setStyleSheet("font-size: 28px; font-weight: bold; color: white;")
        cartao_ativos_layout.addWidget(self.ativos_label)
        cartoes_layout.addWidget(self.cartao_ativos)

        self.cartao_em_compra = QFrame()
        self.cartao_em_compra.setStyleSheet("background-color: #e67e22; border-radius: 8px; padding: 15px;")
        cartao_em_compra_layout = QVBoxLayout(self.cartao_em_compra)
        cartao_em_compra_layout.addWidget(QLabel('🛒 EM COMPRA'))
        self.em_compra_label = QLabel('0')
        self.em_compra_label.setStyleSheet("font-size: 28px; font-weight: bold; color: white;")
        cartao_em_compra_layout.addWidget(self.em_compra_label)
        cartoes_layout.addWidget(self.cartao_em_compra)

        self.cartao_criticos = QFrame()
        self.cartao_criticos.setStyleSheet("background-color: #e74c3c; border-radius: 8px; padding: 15px;")
        cartao_criticos_layout = QVBoxLayout(self.cartao_criticos)
        cartao_criticos_layout.addWidget(QLabel('🔴 CRÍTICOS'))
        self.criticos_label = QLabel('0')
        self.criticos_label.setStyleSheet("font-size: 28px; font-weight: bold; color: white;")
        cartao_criticos_layout.addWidget(self.criticos_label)
        cartoes_layout.addWidget(self.cartao_criticos)

        self.cartao_atencao = QFrame()
        self.cartao_atencao.setStyleSheet("background-color: #f39c12; border-radius: 8px; padding: 15px;")
        cartao_atencao_layout = QVBoxLayout(self.cartao_atencao)
        cartao_atencao_layout.addWidget(QLabel('⚠️ ATENÇÃO'))
        self.atencao_label = QLabel('0')
        self.atencao_label.setStyleSheet("font-size: 28px; font-weight: bold; color: white;")
        cartao_atencao_layout.addWidget(self.atencao_label)
        cartoes_layout.addWidget(self.cartao_atencao)

        cartoes_layout.addStretch()
        scroll_layout.addWidget(cartoes_widget)

        self.inventario_table = QTableWidget()
        self.inventario_table.setColumnCount(12)
        self.inventario_table.setHorizontalHeaderLabels([
            'Foto', 'Código', 'Item', 'Categoria', 'Estoque', 'Mínimo', 'Atenção', 'Local',
            'Validade', 'Status Item', 'Status Estoque', 'Ações'
        ])
        self.inventario_table.horizontalHeader().setStretchLastSection(True)
        self.inventario_table.verticalHeader().setDefaultSectionSize(40)
        self.inventario_table.setAlternatingRowColors(True)
        scroll_layout.addWidget(self.inventario_table)

        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)
        self.tabs.addTab(widget, '📋 Inventário')

    def criar_aba_previsao(self):
        """Aba dedicada exclusivamente à Previsão de Consumo."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(15)
        layout.setContentsMargins(15, 15, 15, 15)

        filtros_widget = QWidget()
        filtros_layout = QFormLayout(filtros_widget)
        filtros_layout.setSpacing(10)
        filtros_layout.setContentsMargins(15, 15, 15, 15)

        self.previsao_filtro = QComboBox()
        self.previsao_filtro.addItems(['Todos', 'Urgente', 'Atenção', 'Normal', 'Ocioso'])
        self.previsao_filtro.setMinimumHeight(35)
        filtros_layout.addRow('Filtrar por status:', self.previsao_filtro)

        btn_gerar = QPushButton('📈 Gerar Previsão de Consumo')
        btn_gerar.setMinimumHeight(40)
        btn_gerar.setStyleSheet("background-color: #1abc9c; color: white; font-weight: bold; padding: 10px;")
        btn_gerar.clicked.connect(self.gerar_relatorio_previsao)
        filtros_layout.addRow('', btn_gerar)
        layout.addWidget(filtros_widget)

        self.previsao_table = QTableWidget()
        self.previsao_table.setColumnCount(9)
        self.previsao_table.setHorizontalHeaderLabels(['Código', 'Item', 'Estoque', 'Mínimo', 'Consumo/Dia', 'Dias Restantes', 'Previsão', 'Status', 'Ação'])
        self.previsao_table.horizontalHeader().setStretchLastSection(True)
        self.previsao_table.verticalHeader().setDefaultSectionSize(30)
        layout.addWidget(self.previsao_table)

        botoes_widget = QWidget()
        botoes_layout = QHBoxLayout(botoes_widget)
        botoes_layout.setSpacing(15)
        btn_exportar = QPushButton('📁 Exportar Relatório')
        btn_exportar.setMinimumHeight(40)
        btn_exportar.setStyleSheet("background-color: #3498db; color: white; font-weight: bold; padding: 10px;")
        btn_exportar.clicked.connect(self.exportar_relatorio_previsao)
        botoes_layout.addWidget(btn_exportar)

        btn_imprimir = QPushButton('🖨️ Imprimir Relatório')
        btn_imprimir.setMinimumHeight(40)
        btn_imprimir.setStyleSheet("background-color: #7f8c8d; color: white; font-weight: bold; padding: 10px;")
        btn_imprimir.clicked.connect(self.imprimir_relatorio_previsao)
        botoes_layout.addWidget(btn_imprimir)

        botoes_layout.addStretch()
        layout.addWidget(botoes_widget)

        self.tabs.addTab(widget, '📈 Previsão de Consumo')

    def criar_aba_backup(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(15)
        layout.setContentsMargins(15, 15, 15, 15)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(20)
        scroll_layout.setContentsMargins(10, 10, 10, 10)

        titulo = QLabel('💾 BACKUP E RESTAURAÇÃO')
        titulo.setStyleSheet("font-size: 18px; font-weight: bold; color: #2c3e50; margin: 10px;")
        scroll_layout.addWidget(titulo)

        info_widget = QWidget()
        info_layout = QFormLayout(info_widget)
        info_layout.setSpacing(10)
        info_layout.setContentsMargins(15, 15, 15, 15)
        self.backup_info = QLabel('Carregando informações...')
        self.backup_info.setStyleSheet("background-color: #f8f9fa; padding: 10px; border-radius: 5px;")
        self.backup_info.setWordWrap(True)
        self.backup_info.setMinimumHeight(80)
        info_layout.addRow('📊 Status:', self.backup_info)
        scroll_layout.addWidget(info_widget)

        botoes_widget = QWidget()
        botoes_layout = QHBoxLayout(botoes_widget)
        botoes_layout.setSpacing(15)

        btn_backup = QPushButton('💾 Criar Backup Agora')
        btn_backup.setMinimumHeight(45)
        btn_backup.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold; padding: 15px; border-radius: 8px; font-size: 14px;")
        btn_backup.clicked.connect(self.criar_backup)
        botoes_layout.addWidget(btn_backup)

        btn_listar = QPushButton('📁 Listar Backups')
        btn_listar.setMinimumHeight(45)
        btn_listar.setStyleSheet("background-color: #3498db; color: white; font-weight: bold; padding: 15px; border-radius: 8px; font-size: 14px;")
        btn_listar.clicked.connect(self.listar_backups)
        botoes_layout.addWidget(btn_listar)

        btn_importar_json = QPushButton('📂 Importar Backup JSON')
        btn_importar_json.setMinimumHeight(45)
        btn_importar_json.setStyleSheet("background-color: #f39c12; color: white; font-weight: bold; padding: 15px; border-radius: 8px; font-size: 14px;")
        btn_importar_json.clicked.connect(self.importar_backup_json)
        botoes_layout.addWidget(btn_importar_json)

        btn_renumerar = QPushButton('🔢 Renumerar Itens')
        btn_renumerar.setMinimumHeight(45)
        btn_renumerar.setStyleSheet("background-color: #9b59b6; color: white; font-weight: bold; padding: 15px; border-radius: 8px; font-size: 14px;")
        btn_renumerar.clicked.connect(self.renumerar_itens_dialog)
        botoes_layout.addWidget(btn_renumerar)

        scroll_layout.addWidget(botoes_widget)

        lista_titulo = QLabel('📋 BACKUPS DISPONÍVEIS')
        lista_titulo.setStyleSheet("font-size: 16px; font-weight: bold; margin-top: 20px;")
        scroll_layout.addWidget(lista_titulo)

        self.backups_table = QTableWidget()
        self.backups_table.setColumnCount(4)
        self.backups_table.setHorizontalHeaderLabels(['Arquivo', 'Data', 'Tamanho', 'Ações'])
        self.backups_table.horizontalHeader().setStretchLastSection(True)
        self.backups_table.verticalHeader().setDefaultSectionSize(30)
        scroll_layout.addWidget(self.backups_table)

        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)
        self.tabs.addTab(widget, '💾 Backup')

    # ========== MÉTODOS AUXILIARES PARA ITENS ==========
    def obter_proximo_codigo(self):
        try:
            self.db.cursor.execute("SELECT MAX(CAST(codigo AS INTEGER)) as max_codigo FROM itens WHERE codigo GLOB '[0-9]*'")
            row = self.db.cursor.fetchone()
            if row and row['max_codigo']:
                proximo = row['max_codigo'] + 1
            else:
                proximo = 1
            return f"{proximo:04d}"
        except Exception as e:
            print(f"Erro ao obter próximo código: {e}")
            return "0001"

    def atualizar_codigo_cadastro(self, index):
        if index == 0:
            self.codigo_input.setText(self.obter_proximo_codigo())

    def processar_selecao_item(self, campo_busca, campo_info, atributo_id):
        texto = campo_busca.text().strip()
        if not texto:
            campo_info.setText('Selecione um item')
            setattr(self, atributo_id, None)
            return

        if '-' in texto:
            codigo_candidato = texto.split('-')[0].strip()
        else:
            codigo_candidato = texto

        itens = self.sistema.buscar_item('codigo_exato', codigo_candidato)
        if len(itens) == 1:
            item = itens[0]
        else:
            itens = self.sistema.buscar_item('nome', texto)
            if len(itens) == 1:
                item = itens[0]
            elif len(itens) > 1:
                self.mostrar_dialogo_itens_para_selecao(itens, campo_busca, campo_info, atributo_id)
                return
            else:
                campo_info.setText('Item não encontrado')
                setattr(self, atributo_id, None)
                return

        self.atualizar_info_item_selecionado(item, campo_info, atributo_id)
        if atributo_id == 'item_saida_mult_id':
            self.atualizar_foto_item(item)
        if hasattr(self, 'saida_mult_qtd') and atributo_id == 'item_saida_mult_id':
            self.saida_mult_qtd.setMaximum(max(0, item.estoque_atual))
            self.saida_mult_qtd.setValue(min(1, item.estoque_atual))

    def mostrar_dialogo_itens_para_selecao(self, itens, campo_busca, campo_info, atributo_id):
        dialog = QDialog(self)
        dialog.setWindowTitle('Selecione o Item')
        dialog.setGeometry(300, 300, 600, 400)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel('Múltiplos itens encontrados. Selecione um:'))
        lista = QListWidget()
        for item in itens:
            item_text = f"{item.codigo} - {item.nome_fantasia} ({item.nome_oficial})"
            list_item = QListWidgetItem(item_text)
            list_item.setData(Qt.UserRole, item.id)
            list_item.setData(Qt.UserRole + 1, item.codigo)
            lista.addItem(list_item)
        layout.addWidget(lista)
        botoes = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botoes.accepted.connect(dialog.accept)
        botoes.rejected.connect(dialog.reject)
        layout.addWidget(botoes)
        if dialog.exec_() == QDialog.Accepted and lista.currentItem():
            item_id = lista.currentItem().data(Qt.UserRole)
            codigo = lista.currentItem().data(Qt.UserRole + 1)
            itens = self.sistema.buscar_item('codigo_exato', codigo)
            if itens:
                self.atualizar_info_item_selecionado(itens[0], campo_info, atributo_id)
                if atributo_id == 'item_saida_mult_id':
                    self.atualizar_foto_item(itens[0])
                campo_busca.setText(f"{codigo} - {itens[0].nome_fantasia}")
                if hasattr(self, 'saida_mult_qtd') and atributo_id == 'item_saida_mult_id':
                    self.saida_mult_qtd.setMaximum(max(0, itens[0].estoque_atual))
                    self.saida_mult_qtd.setValue(min(1, itens[0].estoque_atual))

    def atualizar_info_item_selecionado(self, item, campo_info, atributo_id):
        setattr(self, atributo_id, item.id)
        info_text = f"""
        <b>{item.nome_oficial}</b> ({item.nome_fantasia})<br>
        <b>Código:</b> {item.codigo}<br>
        <b>Estoque:</b> {item.estoque_atual} {item.unidade}<br>
        <b>Mínimo:</b> {item.quantidade_minima}<br>
        <b>Local:</b> {item.local_principal}<br>
        <b>Categoria:</b> {item.categoria}
        """
        if item.estoque_atual <= item.quantidade_minima:
            info_text += '<br><span style="color: red;"><b>⚠️ ESTOQUE CRÍTICO!</b></span>'
        elif item.quantidade_atencao and item.estoque_atual <= item.quantidade_atencao:
            info_text += '<br><span style="color: orange;"><b>⚠️ ESTOQUE EM ATENÇÃO</b></span>'
        campo_info.setText(info_text)

    def atualizar_info_entrada_digito(self):
        texto = self.entrada_busca.text().strip()
        if not texto:
            self.entrada_info.setText('Selecione um item')
            self.item_entrada_id = None
            return

        if '-' in texto:
            codigo_candidato = texto.split('-')[0].strip()
        else:
            codigo_candidato = texto

        itens = self.sistema.buscar_item('codigo_exato', codigo_candidato)
        if len(itens) == 1:
            self.atualizar_info_item_selecionado(itens[0], self.entrada_info, 'item_entrada_id')
        else:
            self.entrada_info.setText('Digite ou selecione um item')

    def atualizar_info_saida_digito(self):
        texto = self.saida_mult_busca.text().strip()
        if not texto:
            self.saida_mult_info.setText('Selecione um item')
            self.item_saida_mult_id = None
            self.atualizar_foto_item(None)
            return

        if '-' in texto:
            codigo_candidato = texto.split('-')[0].strip()
        else:
            codigo_candidato = texto

        itens = self.sistema.buscar_item('codigo_exato', codigo_candidato)
        if len(itens) == 1:
            self.atualizar_info_item_selecionado(itens[0], self.saida_mult_info, 'item_saida_mult_id')
            self.atualizar_foto_item(itens[0])
            self.saida_mult_qtd.setMaximum(max(0, itens[0].estoque_atual))
            self.saida_mult_qtd.setValue(min(1, itens[0].estoque_atual))
        else:
            self.saida_mult_info.setText('Digite ou selecione um item')
            self.item_saida_mult_id = None
            self.atualizar_foto_item(None)

    def on_saida_mult_busca_confirmado(self, text=None):
        if text is not None:
            self.saida_mult_busca.setText(text)
        self.processar_selecao_item(self.saida_mult_busca, self.saida_mult_info, 'item_saida_mult_id')

    # ========== MÉTODOS PARA FOTOS ==========
    def atualizar_foto_item(self, item):
        if item and item.foto:
            pixmap = bytes_para_qpixmap(item.foto, 80, 80)
            self.item_foto_label.setPixmap(pixmap)
        else:
            self.item_foto_label.clear()
            self.item_foto_label.setText('📷')
        self.item_foto_atual = item

    def atualizar_foto_colaborador(self, nome):
        nome_obj = self.sistema.buscar_nome_por_nome(nome)
        if nome_obj and nome_obj.foto:
            pixmap = bytes_para_qpixmap(nome_obj.foto, 50, 50)
            self.colaborador_foto_label.setPixmap(pixmap)
        else:
            self.colaborador_foto_label.clear()
            self.colaborador_foto_label.setText('📷')
        self.colaborador_foto_atual = nome_obj

    def atualizar_foto_colaborador_dinamico(self, texto):
        texto = texto.strip()
        if not texto:
            self.colaborador_foto_label.clear()
            self.colaborador_foto_label.setText('📷')
            self.colaborador_foto_atual = None
            return
        try:
            self.db.cursor.execute(
                'SELECT * FROM nomes WHERE tipo IN ("colaborador", "responsavel") AND nome LIKE ? AND status = "ativo" ORDER BY nome LIMIT 1',
                (f'%{texto}%',)
            )
            row = self.db.cursor.fetchone()
            if row:
                nome_obj = NomeCadastrado(
                    id=row['id'],
                    nome=row['nome'],
                    tipo=row['tipo'],
                    setor=row['setor'],
                    email=row['email'],
                    telefone=row['telefone'],
                    observacoes=row['observacoes'],
                    status=row['status'],
                    foto=row['foto'] if 'foto' in row.keys() else None
                )
                self.atualizar_foto_colaborador(nome_obj.nome)
                self.colaborador_foto_atual = nome_obj
            else:
                self.colaborador_foto_label.clear()
                self.colaborador_foto_label.setText('📷')
                self.colaborador_foto_atual = None
        except Exception as e:
            print(f"Erro ao buscar foto dinâmica: {e}")
            self.colaborador_foto_label.clear()
            self.colaborador_foto_label.setText('📷')

    def atualizar_foto_responsavel_dinamico(self, texto, label, atributo_nome):
        texto = texto.strip()
        if not texto:
            label.clear()
            label.setText('📷')
            setattr(self, atributo_nome, None)
            return
        try:
            self.db.cursor.execute(
                'SELECT * FROM nomes WHERE tipo IN ("responsavel", "colaborador") AND nome LIKE ? AND status = "ativo" ORDER BY nome LIMIT 1',
                (f'%{texto}%',)
            )
            row = self.db.cursor.fetchone()
            if row:
                nome_obj = NomeCadastrado(
                    id=row['id'],
                    nome=row['nome'],
                    tipo=row['tipo'],
                    setor=row['setor'],
                    email=row['email'],
                    telefone=row['telefone'],
                    observacoes=row['observacoes'],
                    status=row['status'],
                    foto=row['foto'] if 'foto' in row.keys() else None
                )
                if nome_obj.foto:
                    pixmap = bytes_para_qpixmap(nome_obj.foto, 50, 50)
                    label.setPixmap(pixmap)
                else:
                    label.clear()
                    label.setText('📷')
                setattr(self, atributo_nome, nome_obj)
            else:
                label.clear()
                label.setText('📷')
                setattr(self, atributo_nome, None)
        except Exception as e:
            print(f"Erro ao buscar foto do responsável: {e}")
            label.clear()
            label.setText('📷')
            setattr(self, atributo_nome, None)

    def atualizar_foto_responsavel_apos_selecao(self, texto, label, atributo_nome):
        self.atualizar_foto_responsavel_dinamico(texto, label, atributo_nome)

    def abrir_foto_responsavel_entrada(self):
        if hasattr(self, 'responsavel_foto_atual_entrada') and self.responsavel_foto_atual_entrada and self.responsavel_foto_atual_entrada.foto:
            self.mostrar_foto_grande(self.responsavel_foto_atual_entrada.foto)

    def abrir_foto_responsavel_saida(self):
        if hasattr(self, 'responsavel_foto_atual_saida') and self.responsavel_foto_atual_saida and self.responsavel_foto_atual_saida.foto:
            self.mostrar_foto_grande(self.responsavel_foto_atual_saida.foto)

    def abrir_foto_item_atual(self):
        if hasattr(self, 'item_foto_atual') and self.item_foto_atual and self.item_foto_atual.foto:
            self.mostrar_foto_grande(self.item_foto_atual.foto)

    def abrir_foto_colaborador_atual(self):
        if hasattr(self, 'colaborador_foto_atual') and self.colaborador_foto_atual and self.colaborador_foto_atual.foto:
            self.mostrar_foto_grande(self.colaborador_foto_atual.foto)

    def on_colaborador_selected(self, text=None):
        if text is None:
            text = self.saida_mult_colaborador.text().strip()
        if not text:
            return
        nome_obj = self.sistema.buscar_nome_por_nome(text)
        if nome_obj and nome_obj.setor:
            self.saida_mult_setor.setText(nome_obj.setor)
        self.atualizar_foto_colaborador(text)

    # ========== NOVOS MÉTODOS PARA O HISTÓRICO ==========
    def atualizar_info_historico_digito(self):
        """Atualiza quando o usuário digita no campo de busca do histórico."""
        texto = self.historico_item_busca.text().strip()
        if not texto:
            self.historico_item_id = None
            return

        # Tenta encontrar um item pelo código exato primeiro
        if '-' in texto:
            codigo_candidato = texto.split('-')[0].strip()
        else:
            codigo_candidato = texto

        itens = self.sistema.buscar_item('codigo_exato', codigo_candidato)
        if len(itens) == 1:
            self.historico_item_id = itens[0].id
        else:
            # Se não encontrar exato pelo código, tenta por nome (pode ser múltiplo)
            itens_nome = self.sistema.buscar_item('nome', texto)
            if len(itens_nome) == 1:
                self.historico_item_id = itens_nome[0].id
            elif len(itens_nome) > 1:
                # Se vários, limpa o ID até que o usuário selecione explicitamente
                self.historico_item_id = None
            else:
                self.historico_item_id = None

    def on_historico_item_selecionado(self):
        """Quando o usuário seleciona um item no completer ou pressiona Enter."""
        texto = self.historico_item_busca.text().strip()
        if not texto:
            self.historico_item_id = None
            return

        # Tenta encontrar pelo código exato
        if '-' in texto:
            codigo_candidato = texto.split('-')[0].strip()
        else:
            codigo_candidato = texto

        itens = self.sistema.buscar_item('codigo_exato', codigo_candidato)
        if len(itens) == 1:
            self.historico_item_id = itens[0].id
            self.carregar_historico()
            return

        # Se não encontrou por código, busca por nome
        itens_nome = self.sistema.buscar_item('nome', texto)
        if len(itens_nome) == 1:
            self.historico_item_id = itens_nome[0].id
            self.carregar_historico()
        elif len(itens_nome) > 1:
            # Múltiplos itens: exibe diálogo para selecionar
            self.mostrar_dialogo_itens_historico(itens_nome)
        else:
            QMessageBox.information(self, "Item não encontrado", "Nenhum item corresponde à busca.")
            self.historico_item_id = None

    def mostrar_dialogo_itens_historico(self, itens):
        """Exibe uma lista para o usuário escolher qual item deseja filtrar."""
        dialog = QDialog(self)
        dialog.setWindowTitle('Selecione o Item')
        dialog.setMinimumWidth(500)
        layout = QVBoxLayout(dialog)

        layout.addWidget(QLabel('Múltiplos itens encontrados. Selecione um:'))
        lista = QListWidget()
        for item in itens:
            item_text = f"{item.codigo} - {item.nome_fantasia} ({item.nome_oficial})"
            list_item = QListWidgetItem(item_text)
            list_item.setData(Qt.UserRole, item.id)
            list_item.setData(Qt.UserRole + 1, item.codigo)
            lista.addItem(list_item)
        layout.addWidget(lista)

        botoes = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botoes.accepted.connect(dialog.accept)
        botoes.rejected.connect(dialog.reject)
        layout.addWidget(botoes)

        if dialog.exec_() == QDialog.Accepted and lista.currentItem():
            item_id = lista.currentItem().data(Qt.UserRole)
            codigo = lista.currentItem().data(Qt.UserRole + 1)
            self.historico_item_id = item_id
            self.historico_item_busca.setText(codigo)  # preenche com o código
            self.carregar_historico()
        else:
            self.historico_item_id = None

    def limpar_filtro_item_historico(self):
        """Limpa o filtro de item e recarrega o histórico."""
        self.historico_item_busca.clear()
        self.historico_item_id = None
        self.carregar_historico()

    # ========== MÉTODOS DE PREVISÃO DE CONSUMO ==========
    def gerar_relatorio_previsao(self):
        try:
            previsoes = self.sistema.gerar_relatorio_previsao_completo()
            filtro = self.previsao_filtro.currentText().lower()
            if filtro != 'todos':
                previsoes = [p for p in previsoes if p.status == filtro]

            self.previsao_table.setRowCount(len(previsoes))
            cores_status = {'urgente': '#e74c3c', 'atencao': '#f39c12', 'normal': '#27ae60', 'ocioso': '#95a5a6', 'erro': '#7f8c8d'}
            for i, prev in enumerate(previsoes):
                self.previsao_table.setItem(i, 0, QTableWidgetItem(prev.codigo))
                self.previsao_table.setItem(i, 1, QTableWidgetItem(prev.nome))
                self.previsao_table.setItem(i, 2, QTableWidgetItem(f"{prev.estoque_atual}"))
                self.previsao_table.setItem(i, 3, QTableWidgetItem(f"{prev.estoque_minimo}"))
                self.previsao_table.setItem(i, 4, QTableWidgetItem(f"{prev.consumo_medio:.2f}"))
                dias_item = QTableWidgetItem(f"{prev.dias_restantes:.1f}")
                if prev.dias_restantes < 7:
                    dias_item.setForeground(QColor('#e74c3c'))
                    dias_item.setFont(QFont('Arial', 10, QFont.Bold))
                elif prev.dias_restantes < 30:
                    dias_item.setForeground(QColor('#f39c12'))
                self.previsao_table.setItem(i, 5, dias_item)
                self.previsao_table.setItem(i, 6, QTableWidgetItem(prev.previsao_reposicao))
                status_item = QTableWidgetItem(prev.status.upper())
                status_item.setForeground(QColor(cores_status.get(prev.status, '#000000')))
                if prev.status in ['urgente', 'atencao']:
                    status_item.setFont(QFont('Arial', 10, QFont.Bold))
                self.previsao_table.setItem(i, 7, status_item)
                acao_text = {
                    'urgente': '🛒 COMPRAR URGENTE',
                    'atencao': '📋 PLANEJAR COMPRA',
                    'ocioso': '👀 MONITORAR'
                }.get(prev.status, '✅ NORMAL')
                self.previsao_table.setItem(i, 8, QTableWidgetItem(acao_text))
            self.previsao_table.resizeColumnsToContents()
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro ao gerar relatório: {str(e)}")

    def exportar_relatorio_previsao(self):
        try:
            data_atual = datetime.now().strftime('%Y%m%d_%H%M%S')
            arquivo, _ = QFileDialog.getSaveFileName(self, "Exportar Relatório de Previsão", f"previsao_consumo_{data_atual}.html", "Arquivos HTML (*.html)")
            if arquivo:
                html = self.gerar_html_previsao()
                with open(arquivo, 'w', encoding='utf-8') as f:
                    f.write(html)
                QMessageBox.information(self, "Sucesso", f"Relatório exportado em:\n{arquivo}")
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro ao exportar: {str(e)}")

    def imprimir_relatorio_previsao(self):
        try:
            html = self.gerar_html_previsao()
            self.imprimir_html(html)
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro ao imprimir: {str(e)}")

    def gerar_html_previsao(self):
        try:
            previsoes = self.sistema.gerar_relatorio_previsao_completo()
            data_atual = datetime.now().strftime('%d/%m/%Y %H:%M')
            contagem_status = {'urgente': 0, 'atencao': 0, 'normal': 0, 'ocioso': 0, 'erro': 0}
            for prev in previsoes:
                contagem_status[prev.status] = contagem_status.get(prev.status, 0) + 1
            html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>Relatório de Previsão de Consumo</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 20px; }}
.header {{ background-color: #2c3e50; color: white; padding: 20px; border-radius: 10px; text-align: center; }}
.resumo {{ background-color: #ecf0f1; padding: 15px; border-radius: 8px; border-left: 5px solid #3498db; }}
table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
th, td {{ padding: 12px; border-bottom: 1px solid #ddd; text-align: left; }}
th {{ background-color: #3498db; color: white; }}
.urgente {{ color: #e74c3c; font-weight: bold; }}
.atencao {{ color: #f39c12; }}
.normal {{ color: #27ae60; }}
.ocioso {{ color: #95a5a6; }}
.status-box {{ display: inline-block; padding: 5px 10px; border-radius: 5px; color: white; font-size: 12px; }}
.urgente-box {{ background-color: #e74c3c; }}
.atencao-box {{ background-color: #f39c12; }}
.normal-box {{ background-color: #27ae60; }}
.ocioso-box {{ background-color: #95a5a6; }}
.footer {{ margin-top: 30px; padding-top: 20px; border-top: 2px solid #ddd; text-align: center; }}
</style>
</head>
<body>
<div class="header"><h1>📈 RELATÓRIO DE PREVISÃO DE CONSUMO</h1><p>Gerado em: {data_atual}</p><p>Total de itens: {len(previsoes)}</p></div>
<div class="resumo"><h3>📊 RESUMO POR STATUS</h3><p>""" + ' '.join([f'<span class="status-box {status}-box">{status.upper()}: {contagem_status.get(status,0)}</span>' for status in ['urgente','atencao','normal','ocioso']]) + f"""</p><p><strong>Itens com necessidade imediata:</strong> {contagem_status['urgente']}</p></div>
<table>
<thead>
<tr><th>Código</th><th>Item</th><th>Estoque</th><th>Mínimo</th><th>Consumo/Dia</th><th>Dias Restantes</th><th>Status</th><th>Ação</th></tr>
</thead>
<tbody>"""
            for prev in previsoes:
                acao = {'urgente':'🛒 COMPRAR URGENTE','atencao':'📋 PLANEJAR COMPRA','ocioso':'👀 MONITORAR'}.get(prev.status, '✅ NORMAL')
                html += f"""<tr><td>{prev.codigo}</td><td>{prev.nome}</td><td>{prev.estoque_atual}</td><td>{prev.estoque_minimo}</td><td>{prev.consumo_medio:.2f}</td><td class="{prev.status}">{prev.dias_restantes:.1f}</td><td><span class="status-box {prev.status}-box">{prev.status.upper()}</span></td><td>{acao}</td></tr>"""
            html += """</tbody></table><div class="footer"><p>Sistema de Almoxarifado</p></div></body></html>"""
            return html
        except Exception as e:
            return f"<h1>Erro: {e}</h1>"

    def imprimir_html(self, html):
        try:
            printer = QPrinter(QPrinter.HighResolution)
            dialog = QPrintDialog(printer, self)
            if dialog.exec_() == QDialog.Accepted:
                document = QTextDocument()
                document.setHtml(html)
                document.print_(printer)
        except Exception as e:
            QMessageBox.warning(self, "Aviso", f"Erro ao imprimir: {str(e)}")

    # ========== CONFIGURAÇÕES E FERRAMENTAS ==========
    def mostrar_configuracoes(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('⚙️ Configurações do Sistema')
        dialog.setGeometry(300, 300, 600, 500)
        layout = QVBoxLayout(dialog)
        layout.setSpacing(15)
        layout.setContentsMargins(15, 15, 15, 15)

        # Grupo 1 - Filtro de Valores Absurdos
        grupo1 = QGroupBox('🔢 Filtro de Valores Absurdos')
        grupo1.setStyleSheet("QGroupBox { font-weight: bold; }")
        grupo1_layout = QFormLayout(grupo1)
        grupo1_layout.setSpacing(10)
        grupo1_layout.setContentsMargins(15, 15, 15, 15)
        self.config_limite_absurdo = QDoubleSpinBox()
        self.config_limite_absurdo.setRange(0, 1000000)
        self.config_limite_absurdo.setDecimals(0)
        self.config_limite_absurdo.setSuffix(' unidades')
        self.config_limite_absurdo.setMinimumHeight(35)
        self.config_limite_absurdo.setValue(self.settings.value('limite_absurdo', 1000, type=int))
        grupo1_layout.addRow('Limite máximo por dia:', self.config_limite_absurdo)
        grupo1_layout.addRow(QLabel('<small>Valores acima deste limite serão ignorados nas análises</small>'))
        layout.addWidget(grupo1)

        # Grupo 2 - Parâmetros de Previsão
        grupo2 = QGroupBox('📅 Parâmetros de Previsão')
        grupo2.setStyleSheet("QGroupBox { font-weight: bold; }")
        grupo2_layout = QFormLayout(grupo2)
        grupo2_layout.setSpacing(10)
        grupo2_layout.setContentsMargins(15, 15, 15, 15)
        self.config_dias_previsao = QSpinBox()
        self.config_dias_previsao.setRange(7, 365)
        self.config_dias_previsao.setSuffix(' dias')
        self.config_dias_previsao.setMinimumHeight(35)
        self.config_dias_previsao.setValue(self.settings.value('dias_previsao', 30, type=int))
        grupo2_layout.addRow('Período de previsão:', self.config_dias_previsao)
        grupo2_layout.addRow(QLabel('<small>Quantos dias à frente prever o consumo</small>'))
        layout.addWidget(grupo2)

        # Grupo 3 - Aparência (Temas)
        grupo3 = QGroupBox('🎨 Aparência')
        grupo3.setStyleSheet("QGroupBox { font-weight: bold; }")
        grupo3_layout = QVBoxLayout(grupo3)
        grupo3_layout.setSpacing(10)
        grupo3_layout.setContentsMargins(15, 15, 15, 15)

        self.tema_group = QButtonGroup()
        tema_layout = QVBoxLayout()
        self.tema_claro = QRadioButton('Claro')
        self.tema_escuro = QRadioButton('Escuro')
        self.tema_azul = QRadioButton('Azul')
        self.tema_amarelo = QRadioButton('Amarelo')
        self.tema_group.addButton(self.tema_claro)
        self.tema_group.addButton(self.tema_escuro)
        self.tema_group.addButton(self.tema_azul)
        self.tema_group.addButton(self.tema_amarelo)
        tema_layout.addWidget(self.tema_claro)
        tema_layout.addWidget(self.tema_escuro)
        tema_layout.addWidget(self.tema_azul)
        tema_layout.addWidget(self.tema_amarelo)

        tema_atual = self.settings.value('tema', 'claro')
        if tema_atual == 'claro':
            self.tema_claro.setChecked(True)
        elif tema_atual == 'escuro':
            self.tema_escuro.setChecked(True)
        elif tema_atual == 'azul':
            self.tema_azul.setChecked(True)
        elif tema_atual == 'amarelo':
            self.tema_amarelo.setChecked(True)

        grupo3_layout.addLayout(tema_layout)
        btn_aplicar_tema = QPushButton('🎨 Aplicar Tema')
        btn_aplicar_tema.setMinimumHeight(35)
        btn_aplicar_tema.clicked.connect(self.aplicar_tema_dialog)
        grupo3_layout.addWidget(btn_aplicar_tema)

        layout.addWidget(grupo3)

        # Grupo 4 - Ferramentas (Apelidos Automáticos)
        grupo4 = QGroupBox('🔧 Ferramentas')
        grupo4.setStyleSheet("QGroupBox { font-weight: bold; }")
        grupo4_layout = QVBoxLayout(grupo4)
        grupo4_layout.setSpacing(10)
        grupo4_layout.setContentsMargins(15, 15, 15, 15)

        btn_gerar_apelidos = QPushButton('🔄 Gerar Apelidos Automáticos para Itens')
        btn_gerar_apelidos.setMinimumHeight(35)
        btn_gerar_apelidos.clicked.connect(self.gerar_apelidos_automaticos)
        grupo4_layout.addWidget(btn_gerar_apelidos)

        label_apelidos = QLabel(
            '<small>Esta ferramenta percorre todos os itens e gera apelidos baseados no nome fantasia.<br>'
            'Inclui: nome em minúsculas/maiúsculas, palavras individuais e siglas.</small>'
        )
        grupo4_layout.addWidget(label_apelidos)

        layout.addWidget(grupo4)

        # Botões de ação
        botoes = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        botoes.accepted.connect(lambda: self.salvar_configuracoes(dialog))
        botoes.rejected.connect(dialog.reject)
        layout.addWidget(botoes)

        dialog.exec_()

    def salvar_configuracoes(self, dialog):
        try:
            self.settings.setValue('limite_absurdo', self.config_limite_absurdo.value())
            self.settings.setValue('dias_previsao', self.config_dias_previsao.value())
            self.db.cursor.execute('INSERT OR REPLACE INTO configuracoes (chave, valor) VALUES (?, ?)',
                                   ('limite_valor_absurdo', str(self.config_limite_absurdo.value())))
            self.db.cursor.execute('INSERT OR REPLACE INTO configuracoes (chave, valor) VALUES (?, ?)',
                                   ('dias_previsao', str(self.config_dias_previsao.value())))
            self.db.conn.commit()
            notificar_dashboard()  # <-- NOTIFICAR DASHBOARD (configurações alteradas)
            QMessageBox.information(dialog, "Sucesso", "Configurações salvas com sucesso!")
            dialog.accept()
        except Exception as e:
            QMessageBox.critical(dialog, "Erro", f"Erro ao salvar configurações: {str(e)}")

    # ========== GERAR APELIDOS AUTOMÁTICOS ==========
    def gerar_apelidos_automaticos(self):
        """Gera apelidos para itens existentes com base no nome fantasia."""
        try:
            opcao = QMessageBox.question(
                self, "Gerar Apelidos",
                "Deseja substituir apelidos já existentes?\n"
                "Escolha 'Sim' para substituir todos.\n"
                "Escolha 'Não' para preencher apenas os itens sem apelidos.\n"
                "Clique em Cancelar para abortar.",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
            )
            if opcao == QMessageBox.Cancel:
                return

            substituir = (opcao == QMessageBox.Yes)

            itens = self.sistema.buscar_item('todos', '')
            if not itens:
                QMessageBox.information(self, "Informação", "Nenhum item encontrado.")
                return

            atualizados = 0
            for item in itens:
                if not substituir and item.apelidos and item.apelidos.strip():
                    continue

                novos_apelidos = self.gerar_apelidos_para_nome(item.nome_fantasia)
                if novos_apelidos:
                    item.apelidos = novos_apelidos
                    self.db.cursor.execute(
                        'UPDATE itens SET apelidos = ? WHERE id = ?',
                        (item.apelidos, item.id)
                    )
                    atualizados += 1

            self.db.conn.commit()
            notificar_dashboard()  # <-- NOTIFICAR DASHBOARD
            QMessageBox.information(
                self, "Concluído",
                f"Apelidos gerados para {atualizados} itens.\n"
                "Recarregue a lista de inventário para ver as alterações."
            )
            self.carregar_itens_autocomplete()
            self.carregar_inventario()
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro ao gerar apelidos: {str(e)}")

    def gerar_apelidos_para_nome(self, nome: str) -> str:
        """Gera uma lista de apelidos a partir do nome."""
        if not nome:
            return ""

        nome_normalizado = unicodedata.normalize('NFKD', nome).encode('ASCII', 'ignore').decode('ASCII')
        nome_minusculo = nome_normalizado.lower()

        apelidos_set = set()

        apelidos_set.add(nome_minusculo)
        apelidos_set.add(nome_minusculo.upper())
        apelidos_set.add(nome_minusculo.capitalize())

        palavras = re.findall(r'\b\w+\b', nome_minusculo)
        for palavra in palavras:
            if len(palavra) > 1:
                apelidos_set.add(palavra)
                apelidos_set.add(palavra.upper())
                apelidos_set.add(palavra.capitalize())
            apelidos_set.add(palavra[0])
            apelidos_set.add(palavra[0].upper())
            if len(palavra) >= 2:
                apelidos_set.add(palavra[:2])
                apelidos_set.add(palavra[:2].upper())

        sigla = ''.join([p[0] for p in palavras if p])
        if sigla and len(sigla) > 1:
            apelidos_set.add(sigla)
            apelidos_set.add(sigla.upper())

        apelidos_list = [a for a in apelidos_set if a and len(a) <= 20]
        apelidos_list = sorted(apelidos_list)

        return ', '.join(apelidos_list)

    # ========== MÉTODOS DE TEMA ==========
    def aplicar_tema(self, tema_id):
        tema = self.TEMAS.get(tema_id, self.TEMAS['claro'])
        paleta = QPalette()
        for role, cor_hex in tema['paleta'].items():
            cor = QColor(cor_hex)
            if role == 'window':
                paleta.setColor(QPalette.Window, cor)
            elif role == 'windowText':
                paleta.setColor(QPalette.WindowText, cor)
            elif role == 'base':
                paleta.setColor(QPalette.Base, cor)
            elif role == 'alternateBase':
                paleta.setColor(QPalette.AlternateBase, cor)
            elif role == 'toolTipBase':
                paleta.setColor(QPalette.ToolTipBase, cor)
            elif role == 'toolTipText':
                paleta.setColor(QPalette.ToolTipText, cor)
            elif role == 'text':
                paleta.setColor(QPalette.Text, cor)
            elif role == 'button':
                paleta.setColor(QPalette.Button, cor)
            elif role == 'buttonText':
                paleta.setColor(QPalette.ButtonText, cor)
            elif role == 'brightText':
                paleta.setColor(QPalette.BrightText, cor)
            elif role == 'highlight':
                paleta.setColor(QPalette.Highlight, cor)
            elif role == 'highlightedText':
                paleta.setColor(QPalette.HighlightedText, cor)
        QApplication.setPalette(paleta)
        self.settings.setValue('tema', tema_id)
        self.status_label.setText(f"Tema alterado para {tema['nome']}")

    def carregar_tema_salvo(self):
        tema_id = self.settings.value('tema', 'claro')
        self.aplicar_tema(tema_id)

    def salvar_tema(self, tema_id):
        self.settings.setValue('tema', tema_id)

    def aplicar_tema_dialog(self):
        for button in self.tema_group.buttons():
            if button.isChecked():
                tema_nome = button.text()
                for tid, data in self.TEMAS.items():
                    if data['nome'] == tema_nome:
                        self.aplicar_tema(tid)
                        break
        QMessageBox.information(self.sender().parent(), "Tema aplicado", "Tema alterado com sucesso!")

    # ========== CARREGAMENTO INICIAL ==========
    def carregar_dados_iniciais(self):
        self.carregar_itens_autocomplete()
        self.carregar_nomes_autocomplete()
        self.carregar_inventario()
        self.carregar_lista_nomes()
        self.atualizar_estatisticas()
        self.atualizar_info_backup()
        self.gerar_relatorio_previsao()

    def carregar_itens_autocomplete(self):
        try:
            itens_ativos = self.sistema.buscar_item('ativos', '')
            itens_compra = self.sistema.buscar_item('em_compra', '')
            itens = itens_ativos + itens_compra
            itens_lista = []
            for item in itens:
                itens_lista.append(f"{item.codigo} - {item.nome_fantasia}")
                itens_lista.append(item.nome_oficial)
                if item.apelidos:
                    for apelido in item.apelidos.split(','):
                        apelido = apelido.strip()
                        if apelido:
                            itens_lista.append(apelido)
            itens_lista = list(set(itens_lista))
            self.entrada_busca.definir_itens(itens_lista)
            self.saida_mult_busca.definir_itens(itens_lista)

            # Preencher autocomplete do histórico
            if hasattr(self, 'historico_item_busca'):
                self.historico_item_busca.definir_itens(itens_lista)

        except Exception as e:
            print(f"Erro ao carregar autocomplete: {e}")

    def carregar_nomes_autocomplete(self):
        try:
            responsaveis = self.sistema.buscar_nomes(tipo='responsavel', status='ativo')
            resp_lista = list(set([r.nome for r in responsaveis]))
            self.entrada_responsavel.definir_itens(resp_lista)
            self.saida_mult_responsavel.definir_itens(resp_lista)

            colaboradores = self.sistema.buscar_nomes(tipo='colaborador', status='ativo')
            colab_lista = list(set([c.nome for c in colaboradores]))
            todos_colab = list(set(colab_lista + resp_lista))
            self.saida_mult_colaborador.definir_itens(todos_colab)
        except Exception as e:
            print(f"Erro ao carregar nomes: {e}")

    def mostrar_todos_itens_entrada(self):
        self.mostrar_dialogo_itens('entrada')

    def mostrar_todos_itens_multipla(self):
        self.mostrar_dialogo_itens('saida_multipla')

    def mostrar_dialogo_itens(self, tipo):
        try:
            itens_ativos = self.sistema.buscar_item('ativos', '')
            itens_compra = self.sistema.buscar_item('em_compra', '')
            itens = itens_ativos + itens_compra
            if not itens:
                QMessageBox.information(self, "Informação", "Nenhum item cadastrado.")
                return
            dialog = QDialog(self)
            dialog.setWindowTitle('Selecionar Item')
            dialog.setGeometry(200, 200, 700, 500)
            layout = QVBoxLayout(dialog)
            layout.setSpacing(15)
            layout.setContentsMargins(15, 15, 15, 15)
            busca = QLineEdit()
            busca.setMinimumHeight(35)
            busca.setPlaceholderText('Digite para filtrar...')
            layout.addWidget(busca)
            lista = QListWidget()
            lista.setAlternatingRowColors(True)
            for item in itens:
                item_text = f"{item.codigo} - {item.nome_fantasia} ({item.nome_oficial})"
                lista_item = QListWidgetItem(item_text)
                lista_item.setData(Qt.UserRole, item.codigo)
                lista_item.setData(Qt.UserRole + 1, item.id)
                lista.addItem(lista_item)
            layout.addWidget(lista)
            busca.textChanged.connect(lambda text: self.filtrar_lista_itens(lista, text, itens))
            botoes = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            botoes.accepted.connect(dialog.accept)
            botoes.rejected.connect(dialog.reject)
            layout.addWidget(botoes)
            lista.itemDoubleClicked.connect(dialog.accept)
            if dialog.exec_() == QDialog.Accepted:
                item_selecionado = lista.currentItem()
                if item_selecionado:
                    codigo = item_selecionado.data(Qt.UserRole)
                    item_id = item_selecionado.data(Qt.UserRole + 1)
                    if tipo == 'entrada':
                        self.entrada_busca.setText(codigo)
                        self.item_entrada_id = item_id
                        self.atualizar_info_entrada_digito()
                    elif tipo == 'saida_multipla':
                        self.saida_mult_busca.setText(codigo)
                        self.item_saida_mult_id = item_id
                        self.atualizar_info_saida_digito()
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro: {str(e)}")

    def filtrar_lista_itens(self, lista_widget, texto, itens):
        lista_widget.clear()
        texto = texto.lower()
        for item in itens:
            if texto in item.codigo.lower() or texto in item.nome_oficial.lower() or texto in item.nome_fantasia.lower():
                item_text = f"{item.codigo} - {item.nome_fantasia} ({item.nome_oficial})"
                lista_item = QListWidgetItem(item_text)
                lista_item.setData(Qt.UserRole, item.codigo)
                lista_item.setData(Qt.UserRole + 1, item.id)
                lista_widget.addItem(lista_item)

    def adicionar_item_saida_multipla(self):
        try:
            if not hasattr(self, 'item_saida_mult_id') or self.item_saida_mult_id is None:
                QMessageBox.warning(self, "Aviso", "Selecione um item primeiro!")
                return
            itens = self.sistema.buscar_item('codigo', '')
            item_encontrado = next((item for item in itens if item.id == self.item_saida_mult_id), None)
            if not item_encontrado:
                QMessageBox.warning(self, "Aviso", "Item não encontrado!")
                return
            quantidade = self.saida_mult_qtd.value()
            for saida_item in self.itens_saida_multipla:
                if saida_item.item_id == self.item_saida_mult_id:
                    saida_item.quantidade += quantidade
                    self.atualizar_tabela_saida_multipla()
                    self.saida_mult_busca.clear()
                    self.saida_mult_qtd.setValue(1)
                    self.saida_mult_obs_item.clear()
                    self.saida_mult_info.setText('Selecione um item')
                    self.atualizar_foto_item(None)
                    return
            saida_item = SaidaMultipla(
                item_id=self.item_saida_mult_id,
                codigo=item_encontrado.codigo,
                nome=item_encontrado.nome_fantasia,
                quantidade=quantidade,
                unidade=item_encontrado.unidade,
                observacoes_item=self.saida_mult_obs_item.text().strip() or None
            )
            self.itens_saida_multipla.append(saida_item)
            self.atualizar_tabela_saida_multipla()
            self.saida_mult_busca.clear()
            self.saida_mult_qtd.setValue(1)
            self.saida_mult_obs_item.clear()
            self.saida_mult_info.setText('Selecione um item')
            self.atualizar_foto_item(None)
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro: {str(e)}")

    def atualizar_tabela_saida_multipla(self):
        self.tabela_itens_saida.setRowCount(len(self.itens_saida_multipla))
        for i, saida_item in enumerate(self.itens_saida_multipla):
            self.tabela_itens_saida.setItem(i, 0, QTableWidgetItem(saida_item.codigo))
            self.tabela_itens_saida.setItem(i, 1, QTableWidgetItem(saida_item.nome))
            self.tabela_itens_saida.setItem(i, 2, QTableWidgetItem(str(saida_item.quantidade)))
            self.tabela_itens_saida.setItem(i, 3, QTableWidgetItem(saida_item.unidade))
            self.tabela_itens_saida.setItem(i, 4, QTableWidgetItem(saida_item.observacoes_item or ''))
            btn_remover = QPushButton('🗑️')
            btn_remover.setStyleSheet("padding: 3px;")
            btn_remover.clicked.connect(partial(self.remover_item_saida_multipla_por_indice, i))
            cell_widget = QWidget()
            layout = QHBoxLayout(cell_widget)
            layout.addWidget(btn_remover)
            layout.setContentsMargins(0, 0, 0, 0)
            self.tabela_itens_saida.setCellWidget(i, 5, cell_widget)
        self.contador_itens.setText(str(len(self.itens_saida_multipla)))

    def remover_item_saida_multipla(self):
        linha = self.tabela_itens_saida.currentRow()
        if linha >= 0:
            self.itens_saida_multipla.pop(linha)
            self.atualizar_tabela_saida_multipla()

    def remover_item_saida_multipla_por_indice(self, indice):
        if 0 <= indice < len(self.itens_saida_multipla):
            self.itens_saida_multipla.pop(indice)
            self.atualizar_tabela_saida_multipla()

    def limpar_lista_saida_multipla(self):
        self.itens_saida_multipla.clear()
        self.atualizar_tabela_saida_multipla()

    def limpar_saida_multipla(self):
        self.limpar_lista_saida_multipla()
        self.saida_mult_busca.clear()
        self.saida_mult_qtd.setValue(1)
        self.saida_mult_obs_item.clear()
        self.saida_mult_info.setText('Selecione um item')
        self.saida_mult_responsavel.clear()
        self.saida_mult_colaborador.clear()
        self.saida_mult_setor.clear()
        self.saida_mult_obs_geral.clear()
        self.atualizar_foto_item(None)
        self.atualizar_foto_colaborador('')
        self.responsavel_foto_label_saida.clear()
        self.responsavel_foto_label_saida.setText('📷')
        if hasattr(self, 'responsavel_foto_atual_saida'):
            self.responsavel_foto_atual_saida = None

    def registrar_saida_multipla(self):
        try:
            if not self.itens_saida_multipla:
                QMessageBox.warning(self, "Aviso", "Adicione pelo menos um item à lista!")
                return
            if not self.saida_mult_responsavel.text().strip():
                QMessageBox.warning(self, "Aviso", "O responsável é obrigatório!")
                return
            if not self.saida_mult_colaborador.text().strip():
                QMessageBox.warning(self, "Aviso", "O colaborador é obrigatório!")
                return

            itens_saida = self.itens_saida_multipla.copy()
            sucesso, mensagem, detalhes = self.sistema.registrar_saida_multipla(
                itens_saida,
                self.saida_mult_responsavel.text().strip(),
                self.saida_mult_colaborador.text().strip(),
                self.saida_mult_setor.text().strip() or None,
                self.saida_mult_obs_geral.toPlainText().strip() or None
            )
            if sucesso:
                resumo = f"✅ Saída registrada para {len(detalhes)} itens!\n\n" + "\n".join(detalhes)
                QMessageBox.information(self, "Sucesso", resumo)
                self.limpar_saida_multipla()
                self.carregar_itens_autocomplete()
                self.carregar_historico()
                self.carregar_inventario()
                self.atualizar_estatisticas()
                self.gerar_relatorio_previsao()
            else:
                erro_texto = f"❌ {mensagem}\n\n" + "\n".join(detalhes)
                QMessageBox.critical(self, "Erro", erro_texto)
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro: {str(e)}")

    def registrar_entrada(self):
        try:
            if not hasattr(self, 'item_entrada_id') or self.item_entrada_id is None:
                QMessageBox.warning(self, "Aviso", "Selecione um item primeiro!")
                return
            if not self.entrada_responsavel.text().strip():
                QMessageBox.warning(self, "Aviso", "O responsável é obrigatório!")
                return

            mov = Movimentacao(
                tipo='entrada',
                item_id=self.item_entrada_id,
                quantidade=self.entrada_qtd.value(),
                responsavel=self.entrada_responsavel.text().strip(),
                fornecedor=self.entrada_fornecedor.text().strip() or None,
                nota_fiscal=self.entrada_nota.text().strip() or None,
                observacoes=self.entrada_obs.toPlainText().strip() or None
            )
            sucesso, mensagem = self.sistema.registrar_movimentacao(mov)
            if sucesso:
                QMessageBox.information(self, "Sucesso", "Entrada registrada com sucesso!")
                self.limpar_entrada()
                self.carregar_itens_autocomplete()
                self.carregar_historico()
                self.carregar_inventario()
                self.atualizar_estatisticas()
                self.gerar_relatorio_previsao()
            else:
                QMessageBox.critical(self, "Erro", mensagem)
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro: {str(e)}")

    # ========== MÉTODOS PARA NOMES ==========
    def salvar_nome(self):
        try:
            if not self.nome_input.text().strip():
                QMessageBox.warning(self, "Aviso", "O nome é obrigatório!")
                return
            tipo = self.nome_tipo.currentText()
            nome = NomeCadastrado(
                id=self.nome_id,
                nome=self.nome_input.text().strip().upper(),
                tipo=tipo,
                setor=self.nome_setor_combo.currentText().strip() or None,
                email=self.nome_email.text().strip() or None,
                telefone=self.nome_telefone.text().strip() or None,
                observacoes=self.nome_observacoes.toPlainText().strip() or None,
                status='ativo' if self.nome_status_ativo.isChecked() else 'inativo',
                foto=self.foto_nome_bytes
            )
            if self.nome_id:
                sucesso, mensagem = self.sistema.atualizar_nome(nome)
            else:
                sucesso, mensagem = self.sistema.cadastrar_nome(nome)
            if sucesso:
                QMessageBox.information(self, "Sucesso", mensagem)
                self.limpar_nome()
                self.carregar_nomes_autocomplete()
                self.carregar_lista_nomes()
            else:
                QMessageBox.critical(self, "Erro", mensagem)
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro: {str(e)}")

    def limpar_nome(self):
        self.nome_id = None
        self.nome_input.clear()
        self.nome_tipo.setCurrentIndex(0)
        self.nome_setor_combo.setCurrentIndex(0)
        self.nome_email.clear()
        self.nome_telefone.clear()
        self.nome_observacoes.clear()
        self.nome_status_ativo.setChecked(True)
        self.nome_btn_salvar.setText('💾 Salvar Nome')
        self.remover_foto_nome()

    def carregar_lista_nomes(self):
        try:
            filtro = self.nome_filtro.currentText()
            tipo = None
            status = None
            if filtro == 'Ativos':
                status = 'ativo'
            elif filtro == 'Inativos':
                status = 'inativo'
            elif filtro in ['Responsável', 'Colaborador', 'Setor', 'Fornecedor']:
                mapa = {'Responsável': 'responsavel', 'Colaborador': 'colaborador', 'Setor': 'setor', 'Fornecedor': 'fornecedor'}
                tipo = mapa.get(filtro)
            nomes = self.sistema.buscar_nomes(tipo=tipo, status=status)
            self.nomes_table.setRowCount(len(nomes))
            for i, nome in enumerate(nomes):
                if nome.foto:
                    pixmap = bytes_para_qpixmap(nome.foto, 40, 40)
                    label_foto = DoubleClickLabel()
                    label_foto.setPixmap(pixmap)
                    label_foto.setFixedSize(40, 40)
                    label_foto.setAlignment(Qt.AlignCenter)
                    label_foto.setStyleSheet("border: 1px solid #ccc; border-radius: 3px;")
                    label_foto.doubleClicked.connect(partial(self.mostrar_foto_grande, nome.foto))
                    self.nomes_table.setCellWidget(i, 0, label_foto)
                else:
                    label_sem_foto = QLabel('📷')
                    label_sem_foto.setFixedSize(40, 40)
                    label_sem_foto.setAlignment(Qt.AlignCenter)
                    label_sem_foto.setStyleSheet("color: #aaa;")
                    self.nomes_table.setCellWidget(i, 0, label_sem_foto)

                nome_cell = QTableWidgetItem(nome.nome)
                if nome.status == 'inativo':
                    nome_cell.setForeground(QColor('#95a5a6'))
                    nome_cell.setToolTip('INATIVO')
                self.nomes_table.setItem(i, 1, nome_cell)

                tipo_display = {'responsavel': 'Responsável', 'colaborador': 'Colaborador', 'setor': 'Setor', 'fornecedor': 'Fornecedor'}
                self.nomes_table.setItem(i, 2, QTableWidgetItem(tipo_display.get(nome.tipo, nome.tipo)))
                self.nomes_table.setItem(i, 3, QTableWidgetItem(nome.setor or '-'))
                self.nomes_table.setItem(i, 4, QTableWidgetItem(nome.email or '-'))
                self.nomes_table.setItem(i, 5, QTableWidgetItem(nome.telefone or '-'))
                status_cell = QTableWidgetItem('✅ Ativo' if nome.status == 'ativo' else '❌ Inativo')
                if nome.status == 'inativo':
                    status_cell.setForeground(QColor('#e74c3c'))
                self.nomes_table.setItem(i, 6, status_cell)

                botoes_widget = QWidget()
                botoes_layout = QHBoxLayout(botoes_widget)
                botoes_layout.setContentsMargins(0, 0, 0, 0)
                btn_editar = QPushButton('✏️')
                btn_editar.setStyleSheet("padding: 3px; background-color: #3498db; color: white;")
                btn_editar.clicked.connect(partial(self.editar_nome, nome))
                botoes_layout.addWidget(btn_editar)
                btn_excluir = QPushButton('🗑️')
                btn_excluir.setStyleSheet("padding: 3px; background-color: #e74c3c; color: white;")
                btn_excluir.clicked.connect(partial(self.excluir_nome_dialog, nome))
                botoes_layout.addWidget(btn_excluir)
                self.nomes_table.setCellWidget(i, 7, botoes_widget)
        except Exception as e:
            print(f"Erro ao carregar nomes: {e}")

    def mostrar_foto_grande(self, dados_bytes):
        if not dados_bytes:
            return
        pixmap = QPixmap()
        pixmap.loadFromData(dados_bytes)
        if pixmap.isNull():
            return
        screen = QDesktopWidget().availableGeometry()
        max_w = min(800, screen.width() - 100)
        max_h = min(600, screen.height() - 100)
        pixmap = pixmap.scaled(max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        dialog = QDialog(self)
        dialog.setWindowTitle("Visualizar Foto")
        layout = QVBoxLayout(dialog)
        label = QLabel()
        label.setPixmap(pixmap)
        layout.addWidget(label)
        btn_fechar = QPushButton("Fechar")
        btn_fechar.clicked.connect(dialog.accept)
        layout.addWidget(btn_fechar)
        dialog.exec_()

    def editar_nome(self, nome):
        self.nome_id = nome.id
        self.nome_input.setText(nome.nome)
        self.nome_tipo.setCurrentText(nome.tipo)
        self.nome_setor_combo.setCurrentText(nome.setor or '')
        self.nome_email.setText(nome.email or '')
        self.nome_telefone.setText(nome.telefone or '')
        self.nome_observacoes.setPlainText(nome.observacoes or '')
        if nome.status == 'ativo':
            self.nome_status_ativo.setChecked(True)
        else:
            self.nome_status_inativo.setChecked(True)
        if nome.foto:
            self.foto_nome_bytes = nome.foto
            pixmap = bytes_para_qpixmap(nome.foto, 120, 120)
            self.foto_nome_label.setPixmap(pixmap)
            self.btn_remover_foto_nome.setEnabled(True)
        else:
            self.remover_foto_nome()
        self.nome_btn_salvar.setText('💾 Atualizar Nome')
        self.tabs.setCurrentIndex(2)
        self.nome_input.setFocus()

    def excluir_nome_dialog(self, nome):
        try:
            resposta = QMessageBox.question(self, "Excluir Nome", f"Tem certeza que deseja excluir o nome:\n\n<b>{nome.nome}</b>\nTipo: {nome.tipo}\n\nEsta ação não poderá ser desfeita!", QMessageBox.Yes | QMessageBox.No)
            if resposta == QMessageBox.Yes:
                sucesso, mensagem = self.sistema.excluir_nome(nome.id)
                if sucesso:
                    QMessageBox.information(self, "Sucesso", mensagem)
                    self.carregar_lista_nomes()
                    self.carregar_nomes_autocomplete()
                else:
                    QMessageBox.critical(self, "Erro", mensagem)
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro: {str(e)}")

    # ========== MÉTODOS PARA EDIÇÃO/EXCLUSÃO/DETALHES NO INVENTÁRIO ==========
    def editar_item(self, item_id: int):
        itens = self.sistema.buscar_item('todos', '')
        item = next((i for i in itens if i.id == item_id), None)
        if not item:
            QMessageBox.warning(self, "Erro", "Item não encontrado!")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(f"✏️ Editar Item: {item.codigo}")
        dialog.setMinimumWidth(600)
        dialog.setMinimumHeight(700)
        layout = QVBoxLayout(dialog)
        layout.setSpacing(15)
        layout.setContentsMargins(15, 15, 15, 15)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        form_widget = QWidget()
        form_layout = QVBoxLayout(form_widget)
        form_layout.setSpacing(20)
        form_layout.setContentsMargins(20, 20, 20, 20)

        # Grupo 1 - Informações Básicas
        grupo1 = QGroupBox('INFORMAÇÕES BÁSICAS')
        grupo1.setStyleSheet("QGroupBox { font-weight: bold; margin-top: 10px; }")
        layout1 = QFormLayout()
        layout1.setSpacing(10)
        layout1.setContentsMargins(15, 15, 15, 15)

        codigo_edit = QLineEdit(item.codigo)
        codigo_edit.setMinimumHeight(35)
        layout1.addRow('🔖 Código do Item *', codigo_edit)

        nome_oficial_edit = QLineEdit(item.nome_oficial)
        nome_oficial_edit.setMinimumHeight(35)
        layout1.addRow('🏷️ Nome Oficial *', nome_oficial_edit)

        nome_fantasia_edit = QLineEdit(item.nome_fantasia)
        nome_fantasia_edit.setMinimumHeight(35)
        layout1.addRow('👤 Nome Fantasia', nome_fantasia_edit)

        apelidos_edit = QLineEdit(item.apelidos or "")
        apelidos_edit.setPlaceholderText('Apelidos separados por vírgula')
        apelidos_edit.setMinimumHeight(35)
        layout1.addRow('🏷️ Apelidos', apelidos_edit)

        categoria_combo = QComboBox()
        categoria_combo.addItems(['', 'Materiais', 'Ferramentas', 'Consumíveis', 'EPI', 'Embalagens', 'Tampas', 'Outros'])
        categoria_combo.setMinimumHeight(35)
        if item.categoria in [categoria_combo.itemText(i) for i in range(categoria_combo.count())]:
            categoria_combo.setCurrentText(item.categoria)
        layout1.addRow('📁 Categoria:', categoria_combo)

        status_combo = QComboBox()
        status_combo.addItems(['Ativo', 'Em Compra', 'Inativo'])
        status_combo.setMinimumHeight(35)
        if item.status == 'ativo':
            status_combo.setCurrentText('Ativo')
        elif item.status == 'em_compra':
            status_combo.setCurrentText('Em Compra')
        else:
            status_combo.setCurrentText('Inativo')
        layout1.addRow('⚡ Status do Item *', status_combo)

        descricao_edit = QTextEdit()
        descricao_edit.setPlainText(item.descricao)
        descricao_edit.setMaximumHeight(100)
        layout1.addRow('📝 Descrição Detalhada:', descricao_edit)

        grupo1.setLayout(layout1)
        form_layout.addWidget(grupo1)

        # Grupo 2 - Controle de Estoque
        grupo2 = QGroupBox('📊 CONTROLE DE ESTOQUE')
        grupo2.setStyleSheet("QGroupBox { font-weight: bold; margin-top: 10px; }")
        layout2 = QFormLayout()
        layout2.setSpacing(10)
        layout2.setContentsMargins(15, 15, 15, 15)

        estoque_minimo = QSpinBox()
        estoque_minimo.setRange(0, 10000)
        estoque_minimo.setValue(item.quantidade_minima)
        estoque_minimo.setMinimumHeight(35)
        layout2.addRow('⚠️ Estoque Mínimo *', estoque_minimo)

        estoque_atencao = QSpinBox()
        estoque_atencao.setRange(0, 10000)
        estoque_atencao.setValue(item.quantidade_atencao or 0)
        estoque_atencao.setSpecialValueText('Opcional')
        estoque_atencao.setMinimumHeight(35)
        layout2.addRow('🔔 Quantidade de Atenção', estoque_atencao)

        unidade_combo = QComboBox()
        unidade_combo.addItems(['Unidade (un)', 'Peça', 'Quilograma (kg)', 'Metro (m)', 'Litro (L)', 'Caixa', 'Pacote', 'Rolo'])
        unidade_combo.setMinimumHeight(35)
        for idx, text in enumerate([unidade_combo.itemText(i) for i in range(unidade_combo.count())]):
            if item.unidade.lower() in text.lower():
                unidade_combo.setCurrentIndex(idx)
                break
        layout2.addRow('⚖️ Unidade de Medida *', unidade_combo)

        estoque_atual = QSpinBox()
        estoque_atual.setRange(0, 100000)
        estoque_atual.setValue(item.estoque_atual)
        estoque_atual.setMinimumHeight(35)
        layout2.addRow('📦 Estoque Atual', estoque_atual)

        grupo2.setLayout(layout2)
        form_layout.addWidget(grupo2)

        # Grupo 3 - Localização
        grupo3 = QGroupBox('📍 LOCALIZAÇÃO')
        grupo3.setStyleSheet("QGroupBox { font-weight: bold; margin-top: 10px; }")
        layout3 = QFormLayout()
        layout3.setSpacing(10)
        layout3.setContentsMargins(15, 15, 15, 15)

        local_principal = QLineEdit(item.local_principal)
        local_principal.setMinimumHeight(35)
        layout3.addRow('🏢 Local Principal *', local_principal)

        local_alternativo = QLineEdit(item.local_alternativo or '')
        local_alternativo.setMinimumHeight(35)
        layout3.addRow('🗺️ Local Alternativo', local_alternativo)

        obs_localizacao = QTextEdit()
        obs_localizacao.setPlainText(item.obs_localizacao or '')
        obs_localizacao.setMaximumHeight(80)
        layout3.addRow('📌 Observações da Localização', obs_localizacao)

        grupo3.setLayout(layout3)
        form_layout.addWidget(grupo3)

        # Grupo 4 - Controle de Validade
        grupo4 = QGroupBox('📅 CONTROLE DE VALIDADE')
        grupo4.setStyleSheet("QGroupBox { font-weight: bold; margin-top: 10px; }")
        layout4 = QHBoxLayout()
        layout4.setSpacing(15)
        layout4.setContentsMargins(15, 15, 15, 15)

        sem_validade = QRadioButton('🕒 Sem validade')
        com_validade = QRadioButton('📆 Com validade')
        data_validade = QDateEdit()
        if item.tem_validade and item.data_validade:
            data_validade.setDate(QDate.fromString(item.data_validade, 'yyyy-MM-dd'))
            com_validade.setChecked(True)
            data_validade.setEnabled(True)
        else:
            sem_validade.setChecked(True)
            data_validade.setEnabled(False)
        data_validade.setDate(data_validade.date() or QDate.currentDate().addYears(1))
        data_validade.setMinimumHeight(35)
        layout4.addWidget(sem_validade)
        layout4.addWidget(com_validade)
        layout4.addWidget(data_validade)
        layout4.addStretch()
        grupo4.setLayout(layout4)
        sem_validade.toggled.connect(lambda checked: data_validade.setEnabled(False))
        com_validade.toggled.connect(lambda checked: data_validade.setEnabled(True))

        form_layout.addWidget(grupo4)

        # Grupo 5 - Foto do Item
        grupo5 = QGroupBox('📸 FOTO DO ITEM')
        grupo5.setStyleSheet("QGroupBox { font-weight: bold; margin-top: 10px; }")
        layout5 = QVBoxLayout()
        layout5.setSpacing(10)
        layout5.setContentsMargins(15, 15, 15, 15)

        foto_label_edit = DoubleClickLabel()
        foto_label_edit.setFixedSize(120, 120)
        foto_label_edit.setStyleSheet("border: 2px dashed #aaa; border-radius: 5px; background-color: #f0f0f0;")
        foto_label_edit.setAlignment(Qt.AlignCenter)
        if item.foto:
            pixmap = bytes_para_qpixmap(item.foto, 120, 120)
            foto_label_edit.setPixmap(pixmap)
            foto_label_edit.setText('')
        else:
            foto_label_edit.setText('🖼️\nClique para\nselecionar')
        foto_label_edit.clicked.connect(lambda: self.selecionar_foto_edicao(item, foto_label_edit))
        foto_label_edit.doubleClicked.connect(lambda: self.mostrar_foto_grande(item.foto) if item.foto else None)
        layout5.addWidget(foto_label_edit, 0, Qt.AlignCenter)

        botoes_foto = QHBoxLayout()
        btn_remover_foto_edit = QPushButton('🗑️ Remover Foto')
        btn_remover_foto_edit.setMinimumHeight(35)
        btn_remover_foto_edit.clicked.connect(lambda: self.remover_foto_edicao(item, foto_label_edit))
        if not item.foto:
            btn_remover_foto_edit.setEnabled(False)
        botoes_foto.addWidget(btn_remover_foto_edit)
        botoes_foto.addStretch()
        layout5.addLayout(botoes_foto)

        grupo5.setLayout(layout5)
        form_layout.addWidget(grupo5)

        # Botões
        botoes_layout = QHBoxLayout()
        botoes_layout.setSpacing(15)

        cancelar_btn = QPushButton('✕ Cancelar')
        cancelar_btn.setMinimumHeight(40)
        cancelar_btn.setStyleSheet("background-color: #95a5a6; color: white; padding: 8px; font-weight: bold;")
        cancelar_btn.clicked.connect(dialog.reject)

        salvar_btn = QPushButton('💾 Salvar Alterações')
        salvar_btn.setMinimumHeight(40)
        salvar_btn.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold; padding: 8px;")
        salvar_btn.clicked.connect(lambda: self.salvar_edicao_item(
            dialog,
            item.id,
            codigo_edit.text().strip(),
            nome_oficial_edit.text().strip(),
            nome_fantasia_edit.text().strip(),
            apelidos_edit.text().strip(),
            categoria_combo.currentText(),
            descricao_edit.toPlainText().strip(),
            status_combo.currentText(),
            estoque_minimo.value(),
            estoque_atencao.value() if estoque_atencao.value() > 0 else None,
            unidade_combo.currentText().split('(')[0].strip().lower()[:2],
            local_principal.text().strip(),
            local_alternativo.text().strip() or None,
            obs_localizacao.toPlainText().strip() or None,
            com_validade.isChecked(),
            data_validade.date().toString('yyyy-MM-dd') if com_validade.isChecked() else None,
            estoque_atual.value(),
            item.foto
        ))

        botoes_layout.addWidget(cancelar_btn)
        botoes_layout.addWidget(salvar_btn)
        form_layout.addLayout(botoes_layout)
        form_layout.addStretch()

        scroll.setWidget(form_widget)
        layout.addWidget(scroll)
        dialog.exec_()

    def selecionar_foto_edicao(self, item, label):
        arquivo, _ = QFileDialog.getOpenFileName(self, "Selecionar Imagem", "", "Imagens (*.png *.jpg *.jpeg *.bmp *.gif)")
        if arquivo:
            dados_bytes = comprimir_imagem(arquivo)
            if dados_bytes:
                item.foto = dados_bytes
                pixmap = bytes_para_qpixmap(dados_bytes, 120, 120)
                label.setPixmap(pixmap)
                parent = label.parent()
                if parent:
                    btn_remover = parent.findChild(QPushButton)
                    if btn_remover:
                        btn_remover.setEnabled(True)

    def remover_foto_edicao(self, item, label):
        item.foto = None
        label.clear()
        label.setText('🖼️\nClique para\nselecionar')
        parent = label.parent()
        if parent:
            btn_remover = parent.findChild(QPushButton)
            if btn_remover:
                btn_remover.setEnabled(False)

    def salvar_edicao_item(self, dialog, item_id, codigo, nome_oficial, nome_fantasia, apelidos, categoria, descricao,
                           status_text, quantidade_minima, quantidade_atencao, unidade, local_principal,
                           local_alternativo, obs_localizacao, tem_validade, data_validade, estoque_atual, foto_atual):
        status_map = {'Ativo': 'ativo', 'Em Compra': 'em_compra', 'Inativo': 'inativo'}
        status = status_map.get(status_text, 'ativo')
        try:
            item = Item(
                id=item_id,
                codigo=codigo,
                nome_oficial=nome_oficial,
                nome_fantasia=nome_fantasia,
                apelidos=apelidos,
                categoria=categoria,
                descricao=descricao,
                status=status,
                quantidade_minima=quantidade_minima,
                quantidade_atencao=quantidade_atencao,
                unidade=unidade,
                local_principal=local_principal,
                local_alternativo=local_alternativo,
                obs_localizacao=obs_localizacao,
                tem_validade=tem_validade,
                data_validade=data_validade,
                estoque_atual=estoque_atual,
                foto=foto_atual
            )
            sucesso, mensagem = self.sistema.atualizar_item(item)
            if sucesso:
                QMessageBox.information(dialog, "Sucesso", mensagem)
                dialog.accept()
                self.carregar_inventario()
                self.carregar_itens_autocomplete()
                self.atualizar_estatisticas()
            else:
                QMessageBox.critical(dialog, "Erro", mensagem)
        except Exception as e:
            QMessageBox.critical(dialog, "Erro", f"Erro ao salvar: {str(e)}")

    def excluir_item(self, item_id: int):
        itens = self.sistema.buscar_item('todos', '')
        item = next((i for i in itens if i.id == item_id), None)
        if not item:
            QMessageBox.warning(self, "Erro", "Item não encontrado!")
            return

        self.db.cursor.execute('SELECT COUNT(*) as total FROM movimentacoes WHERE item_id = ?', (item_id,))
        mov_count = self.db.cursor.fetchone()['total']

        if mov_count > 0:
            resposta = QMessageBox.question(self, "Excluir Item",
                f"O item {item.codigo} possui {mov_count} movimentações.\n\n"
                "Deseja apenas INATIVÁ-lo? (poderá ser reativado depois)\n"
                "Se quiser excluir permanentemente, primeiro remova as movimentações.",
                QMessageBox.Yes | QMessageBox.No)
            if resposta == QMessageBox.Yes:
                sucesso, msg = self.sistema.atualizar_item(Item(
                    id=item.id,
                    codigo=item.codigo,
                    nome_oficial=item.nome_oficial,
                    nome_fantasia=item.nome_fantasia,
                    apelidos=item.apelidos,
                    categoria=item.categoria,
                    descricao=item.descricao,
                    status='inativo',
                    quantidade_minima=item.quantidade_minima,
                    quantidade_atencao=item.quantidade_atencao,
                    unidade=item.unidade,
                    local_principal=item.local_principal,
                    local_alternativo=item.local_alternativo,
                    obs_localizacao=item.obs_localizacao,
                    tem_validade=item.tem_validade,
                    data_validade=item.data_validade,
                    estoque_atual=item.estoque_atual,
                    foto=item.foto
                ))
                if sucesso:
                    QMessageBox.information(self, "Sucesso", "Item inativado com sucesso!")
                    self.carregar_inventario()
                    self.carregar_itens_autocomplete()
                    self.atualizar_estatisticas()
                else:
                    QMessageBox.critical(self, "Erro", msg)
            return
        else:
            resposta = QMessageBox.question(self, "Excluir Item",
                f"Tem certeza que deseja EXCLUIR PERMANENTEMENTE o item {item.codigo}?\n\n"
                "Esta ação não poderá ser desfeita!",
                QMessageBox.Yes | QMessageBox.No)
            if resposta == QMessageBox.Yes:
                try:
                    self.db.cursor.execute('DELETE FROM itens WHERE id = ?', (item_id,))
                    self.db.conn.commit()
                    notificar_dashboard()  # <-- NOTIFICAR DASHBOARD (exclusão)
                    QMessageBox.information(self, "Sucesso", "Item excluído permanentemente!")
                    self.carregar_inventario()
                    self.carregar_itens_autocomplete()
                    self.atualizar_estatisticas()
                except Exception as e:
                    QMessageBox.critical(self, "Erro", f"Erro ao excluir: {str(e)}")

    def ver_detalhes_item(self, item_id: int):
        itens = self.sistema.buscar_item('todos', '')
        item = next((i for i in itens if i.id == item_id), None)
        if not item:
            QMessageBox.warning(self, "Erro", "Item não encontrado!")
            return

        validade_str = item.data_validade if item.tem_validade and item.data_validade else 'Sem validade'
        if item.tem_validade and item.data_validade:
            try:
                data_val = datetime.strptime(item.data_validade, '%Y-%m-%d')
                validade_str = data_val.strftime('%d/%m/%Y')
                dias = (data_val - datetime.now()).days
                if dias < 0:
                    validade_str += ' (VENCIDO)'
                elif dias <= 30:
                    validade_str += f' (vence em {dias} dias)'
            except:
                pass

        cadastro_str = utc_to_local_brasil(item.data_cadastro) if item.data_cadastro else 'Desconhecido'
        atualizacao_str = utc_to_local_brasil(item.data_atualizacao) if item.data_atualizacao else 'Desconhecido'

        status_item_display = {'ativo': 'Ativo', 'em_compra': 'Em Compra', 'inativo': 'Inativo'}.get(item.status, item.status)

        mensagem = f"""
        <b>{item.nome_fantasia}</b><br>
        <i>{item.nome_oficial}</i><br><br>

        <b>🔢 Código:</b> {item.codigo}<br>
        <b>📁 Categoria:</b> {item.categoria or '-'}<br>
        <b>🏷️ Apelidos:</b> {item.apelidos or '-'}<br>
        <b>📊 Estoque Atual:</b> {item.estoque_atual} {item.unidade}<br>
        <b>📍 Localização:</b><br>
        &nbsp;&nbsp;Principal: {item.local_principal}<br>
        &nbsp;&nbsp;Alternativo: {item.local_alternativo or '-'}<br>
        &nbsp;&nbsp;Observação: {item.obs_localizacao or '-'}<br>
        <b>⚡ Status do Item:</b> {status_item_display}<br>
        <b>⚠️ Status do Estoque:</b> {item.calcular_status_estoque().upper()}<br>
        <b>📅 Validade:</b> {validade_str}<br>
        <b>📝 Descrição:</b><br>
        {item.descricao or '-'}<br><br>
        <b>Cadastrado em:</b> {cadastro_str}<br>
        <b>Última atualização:</b> {atualizacao_str}<br>
        """

        QMessageBox.information(self, f"🔍 Detalhes do Item: {item.codigo}", mensagem)

    # ========== OUTROS MÉTODOS ==========
    def salvar_item(self):
        try:
            codigo = self.codigo_input.text().strip()
            if not codigo:
                QMessageBox.warning(self, "Aviso", "Código não gerado automaticamente. Tente novamente.")
                return
            if not self.nome_oficial_input.text().strip():
                QMessageBox.warning(self, "Aviso", "O nome oficial é obrigatório!")
                return
            if not self.nome_fantasia_input.text().strip():
                QMessageBox.warning(self, "Aviso", "O nome fantasia é obrigatório!")
                return
            if not self.local_principal.text().strip():
                QMessageBox.warning(self, "Aviso", "O local principal é obrigatório!")
                return

            status_text = self.status_combo.currentText()
            status_map = {'Ativo': 'ativo', 'Em Compra': 'em_compra', 'Inativo': 'inativo'}
            status = status_map[status_text]

            item = Item(
                codigo=codigo,
                nome_oficial=self.nome_oficial_input.text().strip(),
                nome_fantasia=self.nome_fantasia_input.text().strip(),
                apelidos=self.apelidos_input.text().strip(),
                categoria=self.categoria_combo.currentText(),
                descricao=self.descricao_input.toPlainText().strip(),
                status=status,
                quantidade_minima=self.estoque_minimo.value(),
                quantidade_atencao=self.estoque_atencao.value() if self.estoque_atencao.value() > 0 else None,
                unidade=self.unidade_combo.currentText().split('(')[0].strip().lower()[:2],
                local_principal=self.local_principal.text().strip(),
                local_alternativo=self.local_alternativo.text().strip() or None,
                obs_localizacao=self.obs_localizacao.toPlainText().strip() or None,
                tem_validade=self.com_validade.isChecked(),
                data_validade=self.data_validade.date().toString('yyyy-MM-dd') if self.com_validade.isChecked() else None,
                estoque_atual=0,
                foto=self.foto_item_bytes
            )
            sucesso, mensagem = self.sistema.cadastrar_item(item)
            if sucesso:
                QMessageBox.information(self, "Sucesso", "Item cadastrado com sucesso!")
                self.limpar_cadastro()
                self.carregar_itens_autocomplete()
                self.carregar_inventario()
                self.atualizar_estatisticas()
                self.gerar_relatorio_previsao()
                resposta = QMessageBox.question(self, "Estoque", "Deseja registrar uma entrada para este item?", QMessageBox.Yes | QMessageBox.No)
                if resposta == QMessageBox.Yes:
                    self.tabs.setCurrentIndex(1)
                    self.mov_tabs.setCurrentIndex(0)
                    self.entrada_busca.setText(item.codigo)
                    self.processar_selecao_item(self.entrada_busca, self.entrada_info, 'item_entrada_id')
            else:
                QMessageBox.critical(self, "Erro", mensagem)
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro: {str(e)}")

    def limpar_cadastro(self):
        self.codigo_input.clear()
        self.nome_oficial_input.clear()
        self.nome_fantasia_input.clear()
        self.apelidos_input.clear()
        self.categoria_combo.setCurrentIndex(0)
        self.status_combo.setCurrentIndex(0)
        self.descricao_input.clear()
        self.estoque_minimo.setValue(0)
        self.estoque_atencao.setValue(0)
        self.unidade_combo.setCurrentIndex(0)
        self.local_principal.clear()
        self.local_alternativo.clear()
        self.obs_localizacao.clear()
        self.sem_validade.setChecked(True)
        self.data_validade.setDate(QDate.currentDate().addYears(1))
        self.remover_foto_item()
        self.codigo_input.setText(self.obter_proximo_codigo())

    def limpar_entrada(self):
        self.entrada_busca.clear()
        self.entrada_info.setText('Selecione um item')
        self.entrada_qtd.setValue(1)
        self.entrada_responsavel.clear()
        self.responsavel_foto_label_entrada.clear()
        self.responsavel_foto_label_entrada.setText('📷')
        self.entrada_fornecedor.clear()
        self.entrada_nota.clear()
        self.entrada_obs.clear()
        self.item_entrada_id = None
        if hasattr(self, 'responsavel_foto_atual_entrada'):
            self.responsavel_foto_atual_entrada = None

    # ========== MÉTODO carregar_historico MODIFICADO ==========
    def carregar_historico(self):
        try:
            filtros = {}
            tipo = self.historico_tipo.currentText()
            if tipo != 'Todos':
                filtros['tipo'] = tipo.lower()
            data_de = self.historico_de.date().toString('yyyy-MM-dd')
            data_ate = self.historico_ate.date().toString('yyyy-MM-dd')
            filtros['data_inicio'] = data_de
            filtros['data_fim'] = data_ate

            # Adiciona filtro por item se houver um ID selecionado
            if self.historico_item_id is not None:
                filtros['item_id'] = self.historico_item_id

            movimentacoes = self.sistema.buscar_movimentacoes(filtros)
            self.historico_table.setRowCount(len(movimentacoes))

            cache_fotos = {}

            for i, mov in enumerate(movimentacoes):
                data_local = utc_to_local_brasil(mov['data_movimentacao'])
                self.historico_table.setItem(i, 0, QTableWidgetItem(data_local))
                self.historico_table.setItem(i, 1, QTableWidgetItem(mov['item_nome']))
                self.historico_table.setItem(i, 2, QTableWidgetItem(mov['item_codigo']))
                self.historico_table.setItem(i, 3, QTableWidgetItem('ENTRADA' if mov['tipo'] == 'entrada' else 'SAÍDA'))
                self.historico_table.setItem(i, 4, QTableWidgetItem(str(mov['quantidade'])))
                self.historico_table.setItem(i, 5, QTableWidgetItem(mov['responsavel']))

                # Foto do responsável
                resp_nome = mov['responsavel']
                if resp_nome not in cache_fotos:
                    nome_obj = self.sistema.buscar_nome_por_nome(resp_nome)
                    cache_fotos[resp_nome] = nome_obj.foto if nome_obj else None
                foto_resp = cache_fotos.get(resp_nome)
                if foto_resp:
                    pixmap = bytes_para_qpixmap(foto_resp, 40, 40)
                    label_foto = DoubleClickLabel()
                    label_foto.setPixmap(pixmap)
                    label_foto.setFixedSize(40, 40)
                    label_foto.setAlignment(Qt.AlignCenter)
                    label_foto.setStyleSheet("border: 1px solid #ccc; border-radius: 3px;")
                    label_foto.doubleClicked.connect(partial(self.mostrar_foto_grande, foto_resp))
                    self.historico_table.setCellWidget(i, 6, label_foto)
                else:
                    label_sem_foto = QLabel('📷')
                    label_sem_foto.setFixedSize(40, 40)
                    label_sem_foto.setAlignment(Qt.AlignCenter)
                    label_sem_foto.setStyleSheet("color: #aaa;")
                    self.historico_table.setCellWidget(i, 6, label_sem_foto)

                self.historico_table.setItem(i, 7, QTableWidgetItem(mov['colaborador'] or '-'))

                # Foto do colaborador
                colab_nome = mov['colaborador']
                if colab_nome:
                    if colab_nome not in cache_fotos:
                        nome_obj = self.sistema.buscar_nome_por_nome(colab_nome)
                        cache_fotos[colab_nome] = nome_obj.foto if nome_obj else None
                    foto_colab = cache_fotos.get(colab_nome)
                    if foto_colab:
                        pixmap = bytes_para_qpixmap(foto_colab, 40, 40)
                        label_foto = DoubleClickLabel()
                        label_foto.setPixmap(pixmap)
                        label_foto.setFixedSize(40, 40)
                        label_foto.setAlignment(Qt.AlignCenter)
                        label_foto.setStyleSheet("border: 1px solid #ccc; border-radius: 3px;")
                        label_foto.doubleClicked.connect(partial(self.mostrar_foto_grande, foto_colab))
                        self.historico_table.setCellWidget(i, 8, label_foto)
                    else:
                        label_sem_foto = QLabel('📷')
                        label_sem_foto.setFixedSize(40, 40)
                        label_sem_foto.setAlignment(Qt.AlignCenter)
                        label_sem_foto.setStyleSheet("color: #aaa;")
                        self.historico_table.setCellWidget(i, 8, label_sem_foto)
                else:
                    label_sem_foto = QLabel('📷')
                    label_sem_foto.setFixedSize(40, 40)
                    label_sem_foto.setAlignment(Qt.AlignCenter)
                    label_sem_foto.setStyleSheet("color: #aaa;")
                    self.historico_table.setCellWidget(i, 8, label_sem_foto)

                self.historico_table.setItem(i, 9, QTableWidgetItem(mov['observacoes'] or '-'))

                # Cores de fundo conforme tipo
                for col in range(10):
                    item = self.historico_table.item(i, col)
                    if mov['tipo'] == 'entrada':
                        if item:
                            item.setBackground(QColor(220, 245, 220))
                    else:
                        if item:
                            item.setBackground(QColor(245, 220, 220))
        except Exception as e:
            print(f"Erro ao carregar histórico: {e}")

    def carregar_inventario(self):
        try:
            filtro = self.inventario_filtro.currentText().lower()
            texto = self.inventario_busca.text().strip().lower()
            if filtro == 'todos':
                itens = self.sistema.buscar_item('todos', '')
            elif filtro == 'ativos':
                itens = self.sistema.buscar_item('ativos', '')
            elif filtro == 'em compra':
                itens = self.sistema.buscar_item('em_compra', '')
            elif filtro == 'inativos':
                itens = self.sistema.buscar_item('inativos', '')
            elif filtro == 'críticos':
                itens = self.sistema.buscar_item('criticos', '')
            elif filtro == 'atenção':
                itens = self.sistema.buscar_item('atencao', '')
            elif filtro == 'validade':
                itens = self.sistema.buscar_item('validade', '')
            else:
                itens = self.sistema.buscar_item('todos', '')
            if texto:
                itens = [i for i in itens if texto in i.codigo.lower() or texto in i.nome_oficial.lower() or texto in i.nome_fantasia.lower() or texto in i.local_principal.lower()]
            self.inventario_table.setRowCount(len(itens))
            for i, item in enumerate(itens):
                if item.foto:
                    pixmap = bytes_para_qpixmap(item.foto, 40, 40)
                    label_foto = DoubleClickLabel()
                    label_foto.setPixmap(pixmap)
                    label_foto.setFixedSize(40, 40)
                    label_foto.setAlignment(Qt.AlignCenter)
                    label_foto.setStyleSheet("border: 1px solid #ccc; border-radius: 3px;")
                    label_foto.doubleClicked.connect(partial(self.mostrar_foto_grande, item.foto))
                    self.inventario_table.setCellWidget(i, 0, label_foto)
                else:
                    label_sem_foto = QLabel('📷')
                    label_sem_foto.setFixedSize(40, 40)
                    label_sem_foto.setAlignment(Qt.AlignCenter)
                    label_sem_foto.setStyleSheet("color: #aaa;")
                    self.inventario_table.setCellWidget(i, 0, label_sem_foto)

                self.inventario_table.setItem(i, 1, QTableWidgetItem(item.codigo))
                self.inventario_table.setItem(i, 2, QTableWidgetItem(f"{item.nome_fantasia}\n{item.nome_oficial}"))
                self.inventario_table.setItem(i, 3, QTableWidgetItem(item.categoria or '-'))
                self.inventario_table.setItem(i, 4, QTableWidgetItem(f"{item.estoque_atual} {item.unidade}"))
                self.inventario_table.setItem(i, 5, QTableWidgetItem(str(item.quantidade_minima)))
                self.inventario_table.setItem(i, 6, QTableWidgetItem(str(item.quantidade_atencao) if item.quantidade_atencao else '-'))
                self.inventario_table.setItem(i, 7, QTableWidgetItem(item.local_principal))
                validade_text = ''
                if item.tem_validade and item.data_validade:
                    try:
                        data_validade = datetime.strptime(item.data_validade, '%Y-%m-%d')
                        dias = (data_validade - datetime.now()).days
                        validade_text = data_validade.strftime('%d/%m/%Y')
                        if dias < 0:
                            validade_text += ' (VENCIDO)'
                        elif dias <= 30:
                            validade_text += f' ({dias}d)'
                    except:
                        validade_text = item.data_validade
                self.inventario_table.setItem(i, 8, QTableWidgetItem(validade_text))

                status_item_display = {'ativo': 'ATIVO', 'em_compra': 'EM COMPRA', 'inativo': 'INATIVO'}.get(item.status, item.status.upper())
                item_cor = '#27ae60' if item.status == 'ativo' else ('#e67e22' if item.status == 'em_compra' else '#95a5a6')
                item_status_cell = QTableWidgetItem(status_item_display)
                item_status_cell.setForeground(QColor(item_cor))
                self.inventario_table.setItem(i, 9, item_status_cell)

                if item.status == 'em_compra':
                    status_text = 'EM COMPRA'
                    cor_estoque = '#e67e22'
                else:
                    status_estoque = item.calcular_status_estoque()
                    if status_estoque == 'critico':
                        status_text = 'CRÍTICO'
                        cor_estoque = '#e74c3c'
                    elif status_estoque == 'atencao':
                        status_text = 'ATENÇÃO'
                        cor_estoque = '#f39c12'
                    else:
                        status_text = 'NORMAL'
                        cor_estoque = '#27ae60'
                status_cell = QTableWidgetItem(status_text)
                status_cell.setForeground(QColor(cor_estoque))
                self.inventario_table.setItem(i, 10, status_cell)

                botoes_widget = QWidget()
                botoes_layout = QHBoxLayout(botoes_widget)
                botoes_layout.setContentsMargins(0, 0, 0, 0)
                botoes_layout.setSpacing(5)

                btn_editar = QPushButton('✏️')
                btn_editar.setToolTip('Editar item')
                btn_editar.setFixedSize(28, 28)
                btn_editar.setStyleSheet("background-color: #3498db; color: white; border-radius: 4px;")
                btn_editar.clicked.connect(partial(self.editar_item, item.id))

                btn_excluir = QPushButton('🗑️')
                btn_excluir.setToolTip('Excluir/Inativar item')
                btn_excluir.setFixedSize(28, 28)
                btn_excluir.setStyleSheet("background-color: #e74c3c; color: white; border-radius: 4px;")
                btn_excluir.clicked.connect(partial(self.excluir_item, item.id))

                btn_detalhes = QPushButton('👁️')
                btn_detalhes.setToolTip('Ver detalhes')
                btn_detalhes.setFixedSize(28, 28)
                btn_detalhes.setStyleSheet("background-color: #2ecc71; color: white; border-radius: 4px;")
                btn_detalhes.clicked.connect(partial(self.ver_detalhes_item, item.id))

                botoes_layout.addWidget(btn_editar)
                botoes_layout.addWidget(btn_excluir)
                botoes_layout.addWidget(btn_detalhes)
                self.inventario_table.setCellWidget(i, 11, botoes_widget)

                if item.status == 'inativo':
                    for col in range(1, 11):
                        cell = self.inventario_table.item(i, col)
                        if cell:
                            cell.setBackground(QColor(240, 240, 240))
                if item.tem_validade and item.data_validade:
                    try:
                        data_validade = datetime.strptime(item.data_validade, '%Y-%m-%d')
                        if (data_validade - datetime.now()).days < 0:
                            for col in range(1, 11):
                                cell = self.inventario_table.item(i, col)
                                if cell:
                                    cell.setBackground(QColor(255, 230, 230))
                    except:
                        pass
            self.inventario_table.resizeColumnsToContents()
            self.inventario_table.setColumnWidth(2, 300)
        except Exception as e:
            print(f"Erro ao carregar inventário: {e}")

    def filtrar_inventario(self):
        self.carregar_inventario()

    def limpar_busca_inventario(self):
        self.inventario_busca.clear()
        self.inventario_filtro.setCurrentIndex(0)
        self.carregar_inventario()

    def atualizar_estatisticas(self):
        try:
            stats = self.sistema.obter_estatisticas()
            self.total_label.setText(str(stats.get('total_itens', 0)))
            self.ativos_label.setText(str(stats.get('itens_ativos', 0)))
            self.em_compra_label.setText(str(stats.get('itens_em_compra', 0)))
            self.criticos_label.setText(str(stats.get('itens_criticos', 0)))
            self.atencao_label.setText(str(stats.get('itens_atencao', 0)))
        except Exception as e:
            print(f"Erro ao atualizar estatísticas: {e}")

    def atualizar_info_backup(self):
        try:
            stats = self.sistema.obter_estatisticas()
            info_text = f"""
            <b>📊 Sistema Armazenado Localmente - SQLite</b><br>
            <b>Sistema de Almoxarifado v2.7.4</b><br><br>
            <b>Total de itens:</b> {stats.get('total_itens', 0)}<br>
            <b>Total de movimentações:</b> {stats.get('total_movimentacoes', 0)}<br>
            <b>Último backup:</b> {stats.get('ultimo_backup', 'Nunca')}
            """
            self.backup_info.setText(info_text)
        except Exception as e:
            print(f"Erro ao atualizar info backup: {e}")

    def atualizar_status(self):
        try:
            stats = self.sistema.obter_estatisticas()
            status_text = f"✅ Sistema OK | Itens: {stats.get('total_itens', 0)} | Críticos: {stats.get('itens_criticos', 0)} | Atenção: {stats.get('itens_atencao', 0)} | Em Compra: {stats.get('itens_em_compra', 0)}"
            if stats.get('ultimo_backup'):
                status_text += f" | Último backup: {stats['ultimo_backup']}"
            self.status_label.setText(status_text)
        except Exception as e:
            self.status_label.setText("⚠️ Erro ao atualizar status")

    # ========== EXPORTAÇÃO ==========
    def exportar_inventario_dialog(self):
        try:
            itens = self.sistema.buscar_item('ativos', '')
            dialog = QDialog(self)
            dialog.setWindowTitle('📁 Exportar Inventário')
            dialog.setGeometry(300, 300, 400, 300)
            layout = QVBoxLayout(dialog)
            layout.setSpacing(15)
            layout.setContentsMargins(15, 15, 15, 15)
            label = QLabel(f'Exportar {len(itens)} itens do inventário:')
            layout.addWidget(label)
            btn_csv = QPushButton('📊 Exportar para CSV (Excel)')
            btn_csv.setMinimumHeight(35)
            btn_csv.clicked.connect(lambda: (self.exportar_inventario_csv(itens), dialog.accept()))
            layout.addWidget(btn_csv)
            btn_html = QPushButton('🌐 Exportar para HTML')
            btn_html.setMinimumHeight(35)
            btn_html.clicked.connect(lambda: (self.exportar_inventario_html(itens), dialog.accept()))
            layout.addWidget(btn_html)
            btn_json = QPushButton('📋 Exportar para JSON')
            btn_json.setMinimumHeight(35)
            btn_json.clicked.connect(lambda: (self.exportar_inventario_json(itens), dialog.accept()))
            layout.addWidget(btn_json)
            btn_cancelar = QPushButton('Cancelar')
            btn_cancelar.setMinimumHeight(35)
            btn_cancelar.clicked.connect(dialog.reject)
            layout.addWidget(btn_cancelar)
            dialog.exec_()
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro: {str(e)}")

    def exportar_inventario_csv(self, itens):
        try:
            data_atual = datetime.now().strftime('%Y%m%d_%H%M%S')
            arquivo, _ = QFileDialog.getSaveFileName(self, "Exportar Inventário CSV", f"inventario_{data_atual}.csv", "Arquivos CSV (*.csv)")
            if arquivo:
                with open(arquivo, 'w', newline='', encoding='utf-8') as csvfile:
                    writer = csv.writer(csvfile, delimiter=';')
                    writer.writerow(['Código','Nome Oficial','Nome Fantasia','Apelidos','Categoria','Status','Estoque Atual','Unidade','Estoque Mínimo','Quantidade Atenção','Local Principal','Local Alternativo','Tem Validade','Data Validade','Status Estoque','Tem Foto'])
                    for item in itens:
                        status_estoque = item.calcular_status_estoque()
                        status_item = {'ativo': 'Ativo', 'em_compra': 'Em Compra', 'inativo': 'Inativo'}.get(item.status, item.status)
                        tem_foto = 'Sim' if item.foto else 'Não'
                        writer.writerow([item.codigo, item.nome_oficial, item.nome_fantasia, item.apelidos, item.categoria, status_item, item.estoque_atual, item.unidade, item.quantidade_minima, item.quantidade_atencao or '', item.local_principal, item.local_alternativo or '', 'Sim' if item.tem_validade else 'Não', item.data_validade or '', status_estoque, tem_foto])
                QMessageBox.information(self, "Sucesso", f"Inventário exportado em:\n{arquivo}")
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro ao exportar: {str(e)}")

    def exportar_inventario_html(self, itens):
        try:
            data_atual = datetime.now().strftime('%Y%m%d_%H%M%S')
            arquivo, _ = QFileDialog.getSaveFileName(self, "Exportar Inventário HTML", f"inventario_{data_atual}.html", "Arquivos HTML (*.html)")
            if arquivo:
                data_formatada = datetime.now().strftime('%d/%m/%Y %H:%M')
                html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Inventário - Sistema Almoxarifado</title><style>body {{ font-family: Arial; margin: 20px; }} h1 {{ color: #333; }} table {{ border-collapse: collapse; width: 100%; }} th, td {{ border: 1px solid #ddd; padding: 8px; }} th {{ background-color: #3498db; color: white; }} .critico {{ background-color: #ffebee; }} .atencao {{ background-color: #fff3e0; }} .normal {{ background-color: #e8f5e9; }} .inativo {{ background-color: #f5f5f5; }} .em_compra {{ background-color: #fff9c4; }}</style></head><body><h1>Inventário Completo</h1><p>Data: {data_formatada}</p><p>Total: {len(itens)} itens</p>
<table>
<thead>
<tr><th>Código</th><th>Item</th><th>Apelidos</th><th>Categoria</th><th>Estoque</th><th>Mínimo</th><th>Atenção</th><th>Local</th><th>Validade</th><th>Status</th><th>Foto</th></tr>
</thead>
<tbody>"""
                for item in itens:
                    status_estoque = item.calcular_status_estoque()
                    classe_estoque = status_estoque
                    classe_item = 'inativo' if item.status == 'inativo' else ('em_compra' if item.status == 'em_compra' else 'ativo')
                    status_item = {'ativo': 'Ativo', 'em_compra': 'Em Compra', 'inativo': 'Inativo'}.get(item.status, item.status)
                    tem_foto = 'Sim' if item.foto else 'Não'
                    html += f"<tr class='{classe_item}'>⽭{item.codigo}⽭{item.nome_oficial}<br><small>{item.nome_fantasia}</small>⽭{item.apelidos or '-'}⽭{item.categoria}⽭<td class='{classe_estoque}'>{item.estoque_atual} {item.unidade}⽭{item.quantidade_minima}⽭{item.quantidade_atencao or '-'}⽭{item.local_principal}⽭{item.data_validade or '-'}⽭<td class='{classe_estoque}'>{status_estoque.upper()}<br>({status_item})⽭{tem_foto}</td>"
                html += "</tbody></table></body></html>"
                with open(arquivo, 'w', encoding='utf-8') as f:
                    f.write(html)
                QMessageBox.information(self, "Sucesso", f"HTML exportado em:\n{arquivo}")
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro ao exportar: {str(e)}")

    def exportar_inventario_json(self, itens):
        try:
            data_atual = datetime.now().strftime('%Y%m%d_%H%M%S')
            arquivo, _ = QFileDialog.getSaveFileName(self, "Exportar Inventário JSON", f"inventario_{data_atual}.json", "Arquivos JSON (*.json)")
            if arquivo:
                itens_dict = []
                for item in itens:
                    item_dict = asdict(item)
                    if item_dict['foto']:
                        item_dict['foto'] = base64.b64encode(item_dict['foto']).decode('ascii')
                    itens_dict.append(item_dict)
                dados = {'data_exportacao': datetime.now().isoformat(), 'total_itens': len(itens), 'itens': itens_dict}
                with open(arquivo, 'w', encoding='utf-8') as f:
                    json.dump(dados, f, ensure_ascii=False, indent=2, default=str)
                QMessageBox.information(self, "Sucesso", f"JSON exportado em:\n{arquivo}")
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro ao exportar: {str(e)}")

    def exportar_para_csv(self):
        self.exportar_inventario_dialog()

    def exportar_para_html(self):
        try:
            itens = self.sistema.buscar_item('ativos', '')
            self.exportar_inventario_html(itens)
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro: {str(e)}")

    def exportar_para_pdf(self):
        try:
            dialog = QDialog(self)
            dialog.setWindowTitle('📄 Exportar para PDF')
            dialog.setGeometry(300, 300, 400, 300)
            layout = QVBoxLayout(dialog)
            layout.setSpacing(15)
            layout.setContentsMargins(15, 15, 15, 15)
            label = QLabel('Selecione o relatório para exportar como PDF:')
            layout.addWidget(label)
            btn_inventario = QPushButton('📋 Inventário Completo')
            btn_inventario.setMinimumHeight(35)
            btn_inventario.clicked.connect(lambda: (self.gerar_pdf_inventario(), dialog.accept()))
            layout.addWidget(btn_inventario)
            btn_previsao = QPushButton('📈 Previsão de Consumo')
            btn_previsao.setMinimumHeight(35)
            btn_previsao.clicked.connect(lambda: (self.gerar_pdf_previsao(), dialog.accept()))
            layout.addWidget(btn_previsao)
            btn_cancelar = QPushButton('Cancelar')
            btn_cancelar.setMinimumHeight(35)
            btn_cancelar.clicked.connect(dialog.reject)
            layout.addWidget(btn_cancelar)
            dialog.exec_()
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro: {str(e)}")

    def gerar_pdf_inventario(self):
        try:
            itens = self.sistema.buscar_item('ativos', '')
            data_atual = datetime.now().strftime('%Y%m%d_%H%M%S')
            arquivo, _ = QFileDialog.getSaveFileName(self, "Exportar Inventário PDF", f"inventario_{data_atual}.html", "Arquivos HTML (*.html)")
            if arquivo:
                self.exportar_inventario_html(itens)
                QMessageBox.information(self, "Informação", "Arquivo HTML gerado. Para PDF, use a opção de impressão do navegador e salve como PDF.")
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro ao gerar PDF: {str(e)}")

    def gerar_pdf_previsao(self):
        try:
            html = self.gerar_html_previsao()
            data_atual = datetime.now().strftime('%Y%m%d_%H%M%S')
            arquivo, _ = QFileDialog.getSaveFileName(self, "Exportar Previsão PDF", f"previsao_{data_atual}.html", "Arquivos HTML (*.html)")
            if arquivo:
                with open(arquivo, 'w', encoding='utf-8') as f:
                    f.write(html)
                QMessageBox.information(self, "Informação", "Arquivo HTML gerado. Para PDF, use a opção de impressão do navegador e salve como PDF.")
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro ao gerar PDF: {str(e)}")

    # ========== BACKUP ==========
    def criar_backup(self):
        try:
            resposta = QMessageBox.question(self, "Criar Backup", "Deseja criar um backup do banco de dados agora?", QMessageBox.Yes | QMessageBox.No)
            if resposta == QMessageBox.Yes:
                sucesso, caminho, data = self.db.criar_backup()
                if sucesso:
                    QMessageBox.information(self, "Backup Criado", f"✅ Backup criado com sucesso!\n\nArquivo: {os.path.basename(caminho)}\nData: {data}\nLocal: {caminho}")
                    self.atualizar_info_backup()
                    self.listar_backups()
                else:
                    QMessageBox.critical(self, "Erro no Backup", f"❌ Erro ao criar backup:\n{caminho}")
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro: {str(e)}")

    def listar_backups(self):
        try:
            backups = self.db.listar_backups()
            self.backups_table.setRowCount(len(backups))
            for i, backup in enumerate(backups):
                self.backups_table.setItem(i, 0, QTableWidgetItem(backup['arquivo']))
                self.backups_table.setItem(i, 1, QTableWidgetItem(backup['data']))
                self.backups_table.setItem(i, 2, QTableWidgetItem(backup['tamanho']))
                btn_restaurar = QPushButton('🔄 Restaurar')
                btn_restaurar.setStyleSheet("padding: 5px;")
                btn_restaurar.clicked.connect(partial(self.restaurar_backup, backup))
                btn_excluir = QPushButton('🗑️ Excluir')
                btn_excluir.setStyleSheet("padding: 5px; background-color: #e74c3c; color: white;")
                btn_excluir.clicked.connect(partial(self.excluir_backup, backup))
                widget = QWidget()
                layout = QHBoxLayout(widget)
                layout.addWidget(btn_restaurar)
                layout.addWidget(btn_excluir)
                layout.setContentsMargins(0, 0, 0, 0)
                self.backups_table.setCellWidget(i, 3, widget)
            if not backups:
                self.backups_table.setRowCount(1)
                self.backups_table.setItem(0, 0, QTableWidgetItem("Nenhum backup encontrado"))
        except Exception as e:
            print(f"Erro ao listar backups: {e}")

    def restaurar_backup(self, backup):
        try:
            resposta = QMessageBox.warning(self, "Restaurar Backup", f"⚠️ ATENÇÃO: Esta operação irá SOBRESCREVER o banco de dados atual!\n\nArquivo: {backup['arquivo']}\nData: {backup['data']}\n\nDeseja continuar?", QMessageBox.Yes | QMessageBox.No)
            if resposta == QMessageBox.Yes:
                self.db.close()
                data_atual = datetime.now().strftime('%Y%m%d_%H%M%S')
                backup_atual = os.path.join(BACKUP_DIR, f'pre_restauracao_{data_atual}.db')
                shutil.copy2(DATABASE_PATH, backup_atual)
                shutil.copy2(backup['caminho'], DATABASE_PATH)
                self.db.connect()
                self.sistema = SistemaAlmoxarifado(self.db)
                QMessageBox.information(self, "Backup Restaurado", f"✅ Backup restaurado com sucesso!\n\nUm backup do banco anterior foi salvo como:\n{os.path.basename(backup_atual)}")
                self.carregar_dados_iniciais()
                self.listar_backups()
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro ao restaurar backup: {str(e)}")
            self.db.connect()

    def excluir_backup(self, backup):
        try:
            resposta = QMessageBox.question(self, "Excluir Backup", f"Tem certeza que deseja excluir o backup?\n\nArquivo: {backup['arquivo']}\nData: {backup['data']}", QMessageBox.Yes | QMessageBox.No)
            if resposta == QMessageBox.Yes:
                os.remove(backup['caminho'])
                QMessageBox.information(self, "Backup Excluído", "✅ Backup excluído com sucesso!")
                self.listar_backups()
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro ao excluir backup: {str(e)}")

    # ========== RENUMERAR ITENS ==========
    def renumerar_itens_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('Renumerar Itens')
        dialog.setMinimumWidth(500)
        layout = QVBoxLayout(dialog)
        layout.setSpacing(15)

        layout.addWidget(QLabel('⚠️ Esta operação irá alterar TODOS os códigos dos itens existentes!'))
        layout.addWidget(QLabel('Recomenda-se fazer um backup antes.'))

        grupo_ordem = QGroupBox('Ordenação dos itens')
        ordem_layout = QVBoxLayout()
        self.ordem_data = QRadioButton('Por data de cadastro (mais antigo primeiro)')
        self.ordem_data.setChecked(True)
        self.ordem_id = QRadioButton('Por ID (crescente)')
        ordem_layout.addWidget(self.ordem_data)
        ordem_layout.addWidget(self.ordem_id)
        grupo_ordem.setLayout(ordem_layout)
        layout.addWidget(grupo_ordem)

        grupo_formato = QGroupBox('Formato do novo código')
        formato_layout = QVBoxLayout()
        self.formato_sequencial = QRadioButton('Sequencial numérico (0001, 0002, …)')
        self.formato_sequencial.setChecked(True)
        formato_layout.addWidget(self.formato_sequencial)
        grupo_formato.setLayout(formato_layout)
        layout.addWidget(grupo_formato)

        layout.addWidget(QLabel('🔍 Nota: as movimentações continuarão vinculadas corretamente (usam ID).'))

        botoes = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botoes.accepted.connect(lambda: self.executar_renumeracao(dialog))
        botoes.rejected.connect(dialog.reject)
        layout.addWidget(botoes)

        dialog.exec_()

    def executar_renumeracao(self, dialog):
        try:
            sucesso_backup, caminho_backup, _ = self.db.criar_backup()
            if not sucesso_backup:
                QMessageBox.critical(self, "Erro", "Não foi possível criar o backup. Operação cancelada.")
                return

            ordem = 'data_cadastro' if self.ordem_data.isChecked() else 'id'

            sucesso, mensagem = self.db.renumerar_itens(ordem)

            if sucesso:
                QMessageBox.information(self, "Sucesso",
                    f"✅ {mensagem}\n"
                    f"Backup criado em: {os.path.basename(caminho_backup)}")
                self.carregar_dados_iniciais()
                dialog.accept()
            else:
                QMessageBox.critical(self, "Erro", mensagem)
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro inesperado: {str(e)}")

    # ========== IMPORTAR JSON ==========
    def importar_backup_json(self):
        try:
            arquivo, _ = QFileDialog.getOpenFileName(self, "Selecionar Backup JSON", "", "Arquivos JSON (*.json)")
            if not arquivo:
                return

            resposta = QMessageBox.question(self, "Importar Backup", 
                "⚠️ ATENÇÃO: Esta operação irá IMPORTAR os dados do arquivo JSON para o banco atual.\n"
                "Itens e movimentações com IDs conflitantes serão substituídos (INSERT OR REPLACE).\n\n"
                "A tabela de nomes NÃO será afetada.\n\n"
                "Deseja continuar?",
                QMessageBox.Yes | QMessageBox.No)

            if resposta == QMessageBox.Yes:
                sucesso, mensagem = self.db.importar_backup_json(arquivo)
                if sucesso:
                    QMessageBox.information(self, "Sucesso", mensagem)
                    self.carregar_dados_iniciais()
                else:
                    QMessageBox.critical(self, "Erro", mensagem)
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro ao importar: {str(e)}")

    def mostrar_sobre(self):
        QMessageBox.about(self, "Sobre o Sistema",
            "Sistema de Almoxarifado\n\n"
            "Versão: 2.7.4\n"
            "Desenvolvido para controle completo de estoque\n\n"
            "✅ Funcionalidade de fotos adicionada!\n"
            "   • Itens e funcionários podem ter fotos anexadas\n"
            "   • Imagens são comprimidas (redimensionadas e com qualidade reduzida)\n"
            "   • Armazenadas no banco SQLite como BLOB\n"
            "   • Miniaturas exibidas nos formulários e tabelas\n"
            "   • Clique duplo na foto para ver versão ampliada\n"
            "   • Fotos maiores na saída múltipla (80x80 item, 50x50 responsável/colaborador)\n"
            "✅ Apelidos adicionados ao cadastro de itens\n"
            "   • Campo para nomes alternativos separados por vírgula\n"
            "   • Apelidos são considerados na busca\n"
            "✅ Layout reformulado com fonte maior e espaçamentos\n"
            "✅ Geração automática de código e renumeracão de itens\n"
            "✅ Horários convertidos para fuso Brasil\n"
            "✅ Temas personalizáveis (claro, escuro, azul, amarelo)\n"
            "✅ NOVO: Foto do colaborador aparece/desaparece ao digitar na saída múltipla\n"
            "✅ NOVO: Foto do responsável na entrada e na saída múltipla (atualização dinâmica)\n"
            "✅ NOVO: Geração automática de apelidos para itens existentes (ferramenta na aba Configurações)\n"
            "✅ NOVO: Aba histórico exibe fotos do responsável e do colaborador\n"
            "✅ NOVO: Tamanhos das fotos padronizados (50x50 para pessoas, 80x80 para itens na saída)\n"
            "✅ NOVO: Histórico pode ser filtrado por item específico (busca por código, nome ou apelido)\n"
            "✅ INTEGRAÇÃO COM DASHBOARD: Notifica servidor Node.js após cada alteração\n\n"
            "💾 Sistema armazenado localmente - SQLite")

    def closeEvent(self, event):
        self.db.close()
        event.accept()

def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setApplicationName("Sistema de Almoxarifado")
    app.setApplicationVersion("2.7.4")
    janela = JanelaPrincipal()
    janela.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()