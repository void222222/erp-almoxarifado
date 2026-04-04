Documentação do Sistema de Almoxarifado – Versão 2.7.4
📋 Sumário

    Visão Geral

    Funcionalidades

    Tecnologias Utilizadas

    Estrutura do Projeto

    Banco de Dados

    Instalação e Execução

    Interface Gráfica

    Operações Detalhadas

        Cadastro de Itens

        Movimentações (Entrada, Saída Múltipla, Histórico)

        Cadastro de Nomes

        Inventário

        Previsão de Consumo

        Backup e Restauração

    Funcionalidades Especiais

        Fotos dos Itens e Pessoas

        Apelidos para Itens

        Temas Personalizáveis

        Integração com Dashboard

    Detalhes Técnicos

    Personalização e Configurações

    Possíveis Melhorias

Visão Geral

O Sistema de Almoxarifado é uma aplicação desktop desenvolvida em Python com PyQt5 para controle completo de estoque. Ele permite cadastrar itens, registrar entradas e saídas (inclusive múltiplas), gerenciar colaboradores e responsáveis, visualizar inventário com status (crítico, atenção, normal), prever consumo baseado em histórico e realizar backup/restauração do banco de dados. O sistema também suporta fotos para itens e pessoas, busca por apelidos e temas personalizáveis.

A versão atual (2.7.4) inclui funcionalidades avançadas como:

    Fotos comprimidas armazenadas no banco SQLite.

    Exibição de miniaturas e visualização ampliada com duplo clique.

    Campo "Apelidos" no cadastro de itens, usado na busca.

    Geração automática de apelidos para itens existentes.

    Filtro de histórico por item específico.

    Integração com dashboard via notificações HTTP.

Funcionalidades
Cadastro de Itens

    Código automático sequencial (ex: 0001, 0002...).

    Campos: nome oficial, nome fantasia, apelidos (separados por vírgula), categoria, descrição, status (ativo/em compra/inativo).

    Controle de estoque: quantidade mínima, quantidade de atenção, unidade.

    Localização: local principal, alternativo, observações.

    Controle de validade (com ou sem data).

    Foto do item (comprime e armazena no banco).

    Edição, exclusão (ou inativação) e visualização de detalhes.

Movimentações

    Entrada de itens: seleção do item (com autocomplete), responsável (com foto), fornecedor, nota fiscal, observações.

    Saída múltipla: adicionar vários itens em uma única transação, com foto do item, responsável (foto), colaborador (foto), setor e observações por item e gerais.

    Histórico: listagem de todas as movimentações, com filtros por tipo, período e item específico. Exibe fotos do responsável e do colaborador em miniaturas (duplo clique amplia).

Cadastro de Nomes (Responsáveis, Colaboradores, Fornecedores)

    Nome, tipo, setor, email, telefone, observações, status (ativo/inativo).

    Foto da pessoa (comprime e armazena).

    Utilizado nos campos de autocomplete de responsável e colaborador nas movimentações.

    Exibição da foto em tempo real nos formulários de entrada/saída.

Inventário

    Tabela completa com todos os itens, mostrando foto, código, nome, categoria, estoque, mínimo, atenção, local, validade, status do item e status do estoque (normal/atenção/crítico).

    Filtros por status (ativos, em compra, inativos, críticos, atenção, validade) e busca textual (nome, código, local).

    Cards resumo: total de itens, ativos, em compra, críticos, atenção.

    Ações de editar, excluir/inativar e ver detalhes em cada linha.

Previsão de Consumo

    Calcula consumo médio diário com base nos últimos 90 dias (valores absurdos acima de limite configurável são ignorados).

    Gera previsão de quantos dias o estoque atual durará, considerando o estoque mínimo.

    Classifica itens em: urgente (<7 dias), atenção (7-30 dias), normal (>30 dias) ou ocioso (sem consumo).

    Relatório em tabela com exportação para HTML e impressão.

    Gráfico de histórico de consumo (disponível futuramente).

Backup e Restauração

    Criação de backup manual do banco de dados SQLite.

    Listagem de backups existentes com data, tamanho e opções de restaurar/excluir.

    Importação de backup a partir de arquivo JSON (formato exportado).

    Renumeração de itens (reordena códigos) com backup automático antes da operação.

Configurações

    Limite de valor absurdo (para filtro de consumo).

    Período de previsão (dias).

    Seleção de temas (claro, escuro, azul, amarelo).

    Ferramenta de geração automática de apelidos para itens existentes.

Tecnologias Utilizadas

    Python 3.7+ – linguagem principal.

    PyQt5 – interface gráfica.

    SQLite3 – banco de dados embutido.

    Pillow (PIL) – compressão de imagens (opcional, mas recomendado).

    Requests – envio de notificações para dashboard.

    Pytz / ZoneInfo – conversão de fusos horários.

    Statistics – cálculos estatísticos para consumo.

Estrutura do Projeto
text

Almoxarifado/
├── almoxarifado.py              # Código principal do sistema
├── data/                        # Diretório de dados (criado automaticamente)
│   └── almoxarifado.db          # Banco SQLite
├── backups/                      # Backups do banco
├── exportacoes/                   # Exportações (CSV, HTML, JSON)
├── relatorios/                    # Relatórios gerados
└── (ícones, imagens, etc.)        # Opcional

O código é autocontido; as pastas são criadas na primeira execução.
Banco de Dados

O sistema utiliza SQLite com as seguintes tabelas:
itens
Coluna	Tipo	Descrição
id	INTEGER	PK
codigo	TEXT	Código único do item
nome_oficial	TEXT	Nome oficial
nome_fantasia	TEXT	Nome fantasia
apelidos	TEXT	Apelidos separados por vírgula
categoria	TEXT	Categoria
descricao	TEXT	Descrição
status	TEXT	ativo / em_compra / inativo
quantidade_minima	INTEGER	Estoque mínimo
quantidade_atencao	INTEGER	Quantidade de atenção (opcional)
unidade	TEXT	Unidade de medida
local_principal	TEXT	Local principal
local_alternativo	TEXT	Local alternativo
obs_localizacao	TEXT	Observações de localização
tem_validade	INTEGER	0 ou 1
data_validade	DATE	Data de validade (se aplicável)
estoque_atual	INTEGER	Quantidade em estoque
data_cadastro	TIMESTAMP	Data de criação
data_atualizacao	TIMESTAMP	Última atualização
foto	BLOB	Foto do item (comprimida)
nomes
Coluna	Tipo	Descrição
id	INTEGER	PK
nome	TEXT	Nome da pessoa
tipo	TEXT	responsavel / colaborador / fornecedor
setor	TEXT	Setor/departamento
email	TEXT	Email
telefone	TEXT	Telefone
observacoes	TEXT	Observações
status	TEXT	ativo / inativo
data_cadastro	TIMESTAMP	Data de cadastro
foto	BLOB	Foto da pessoa (comprimida)
movimentacoes
Coluna	Tipo	Descrição
id	INTEGER	PK
tipo	TEXT	entrada / saida
item_id	INTEGER	FK → itens.id
quantidade	INTEGER	Quantidade movimentada
responsavel	TEXT	Nome do responsável (cópia)
colaborador	TEXT	Nome do colaborador (para saída)
setor_colaborador	TEXT	Setor do colaborador
fornecedor	TEXT	Fornecedor (entrada)
nota_fiscal	TEXT	Nota fiscal (entrada)
observacoes	TEXT	Observações gerais
observacoes_item	TEXT	Observações específicas do item (saída)
data_movimentacao	TIMESTAMP	Data/hora da movimentação (UTC)
configuracoes
Chave	Valor	Descrição
chave	TEXT	Nome da configuração
valor	TEXT	Valor
data_atualizacao	TIMESTAMP	Última atualização

Configurações padrão: sistema_nome, sistema_versao, empresa_nome, ultimo_backup, total_itens, total_movimentacoes, limite_valor_absurdo, dias_previsao.
Instalação e Execução
Pré-requisitos

    Python 3.7 ou superior.

    Bibliotecas: PyQt5, requests, Pillow (opcional, mas recomendado), pytz (se zoneinfo não disponível).

    Para comprimir imagens, instale Pillow: pip install Pillow.

Instalação das dependências
bash

pip install PyQt5 requests Pillow pytz

Execução

    Salve o código em um arquivo, por exemplo almoxarifado.py.

    Execute:
    bash

    python almoxarifado.py

    Na primeira execução, o banco de dados e as pastas são criados automaticamente.

Criando um executável (opcional)

Use PyInstaller para gerar um .exe (Windows) ou executável Linux/macOS:
bash

pip install pyinstaller
pyinstaller --onefile --windowed --icon=icone.ico almoxarifado.py

Coloque o executável em uma pasta e ele criará as subpastas ao ser executado.
Interface Gráfica

A janela principal possui abas organizadas:

    📦 Cadastrar – Formulário completo para cadastro de itens.

    🔄 Movimentações – Sub-abas: Entrada, Saída Múltipla, Histórico.

    👥 Nomes – Cadastro de pessoas (responsáveis, colaboradores, fornecedores).

    📋 Inventário – Visualização de todos os itens com filtros e cards estatísticos.

    📈 Previsão de Consumo – Relatório de previsão com opções de exportação.

    💾 Backup – Gerenciamento de backups e restauração.

Detalhes da Interface

    Campos de autocomplete em todos os lugares onde se seleciona item ou nome.

    Miniaturas de fotos (50×50 para pessoas, 80×80 para itens na saída) aparecem dinamicamente.

    Clique duplo na miniatura abre a foto em tamanho maior.

    Temas podem ser alterados nas configurações.

    Barra de status exibe informações atualizadas periodicamente.

Operações Detalhadas
Cadastro de Itens

    Preencha os campos obrigatórios (nome oficial, nome fantasia, local principal).

    O código é gerado automaticamente com base no último código numérico.

    Opcional: adicione apelidos separados por vírgula.

    Selecione uma foto clicando na área de imagem (suporte a PNG, JPG, etc.). A imagem é redimensionada para no máximo 800px e comprimida em JPEG com qualidade 80%.

    Clique em 💾 Salvar Item. Após salvar, o sistema pergunta se deseja registrar uma entrada.

Movimentações
Entrada

    Digite parte do código ou nome do item. O autocomplete sugere itens ativos e em compra.

    Ao selecionar, as informações do item aparecem.

    Digite o responsável; a foto (se existir) é carregada automaticamente ao digitar.

    Preencha quantidade, fornecedor, nota fiscal e observações.

    Clique em ✅ Registrar Entrada. O estoque é atualizado e, se o item estava "Em Compra" e o novo estoque ultrapassar o mínimo, o status volta a "Ativo".

Saída Múltipla

    Adicione itens um a um: digite o item, veja a foto e informações, defina quantidade e observações específicas, clique em ➕ ADICIONAR À LISTA.

    Os itens adicionados aparecem em uma tabela, com opção de remover.

    Preencha responsável (com foto dinâmica), colaborador (com foto dinâmica) e setor (preenchido automaticamente se o colaborador tiver setor cadastrado).

    Adicione observações gerais.

    Clique em ✅ REGISTRAR SAÍDA MÚLTIPLA. Todos os itens são baixados do estoque em uma única transação.

Histórico

    Use os filtros de tipo (entrada/saída), período e item específico.

    A tabela exibe data convertida para horário brasileiro, fotos do responsável e colaborador (duplo clique amplia).

    Linhas coloridas: verde para entradas, vermelho para saídas.

Cadastro de Nomes

    Preencha nome, tipo, setor, contatos e foto.

    Ao digitar um nome nos campos de responsável/colaborador, a foto é carregada automaticamente.

    Na lista de nomes, é possível editar ou excluir (somente se não houver movimentações vinculadas).

Inventário

    A tabela é atualizada automaticamente com base nos filtros e busca.

    Status do estoque: crítico (estoque ≤ mínimo), atenção (estoque ≤ atenção e > mínimo), normal.

    Itens inativos aparecem em cinza; itens com validade vencida ou próxima ao vencimento têm fundo avermelhado.

    Ações: editar (abre diálogo), excluir/inativar (confirmação) e detalhes (pop-up com informações completas).

Previsão de Consumo

    O relatório é gerado automaticamente ao abrir a aba.

    Utilize o filtro de status para visualizar apenas itens urgentes, em atenção, etc.

    A tabela mostra código, nome, estoque, mínimo, consumo médio por dia, dias restantes, previsão e ação sugerida.

    Botões para exportar para HTML e imprimir (abre diálogo de impressão).

Backup e Restauração

    Criar Backup: faz uma cópia do banco de dados na pasta backups com timestamp.

    Listar Backups: mostra todos os backups existentes com opções de restaurar (substitui o banco atual) e excluir.

    Importar Backup JSON: permite importar um arquivo JSON exportado anteriormente (pode ser útil para migração).

    Renumerar Itens: reordena os códigos dos itens com base na data de cadastro ou ID, criando um backup automático antes.

Funcionalidades Especiais
Fotos dos Itens e Pessoas

    Compressão: Ao selecionar uma imagem, ela é redimensionada para no máximo 800×800 e convertida para JPEG com qualidade 80% (se Pillow instalado). Caso contrário, armazena o binário original.

    Armazenamento: Os bytes da imagem são guardados no campo BLOB da respectiva tabela.

    Exibição: Miniaturas são geradas com bytes_para_qpixmap(); ao clicar duas vezes, abre um diálogo com a imagem em tamanho maior (limitado à tela).

    Tamanhos padronizados:

        Pessoas (cadastro e exibições): 50×50 (miniaturas).

        Itens na saída múltipla: 80×80.

        Itens no inventário: 40×40.

Apelidos para Itens

    Campo apelidos no cadastro, aceita texto livre (ex: "caneta, bic, esferográfica").

    Na busca por nome (buscar_item('nome', ...)) a consulta inclui os apelidos.

    Ferramenta em Configurações → Gerar Apelidos Automáticos percorre todos os itens e gera apelidos baseados no nome fantasia (minúsculas, maiúsculas, palavras individuais, siglas). O usuário pode optar por substituir existentes ou apenas preencher os vazios.

Temas Personalizáveis

    Quatro temas: Claro, Escuro, Azul, Amarelo.

    As cores são definidas em TEMAS e aplicadas via QPalette.

    O tema escolhido é salvo nas configurações do usuário (QSettings) e restaurado na próxima execução.

Integração com Dashboard

    Após qualquer operação que altere o banco (cadastro, edição, movimentação, exclusão, backup, importação), o sistema chama a função notificar_dashboard().

    Essa função envia uma requisição POST para http://localhost:3000/update com timeout de 0,5 segundos.

    Se o servidor Node.js do dashboard estiver rodando, ele recebe a notificação e pode atualizar seus dados em tempo real.

    A falha na notificação (servidor offline) é ignorada, não interrompe o sistema.

Detalhes Técnicos
Classes Principais

    Item, NomeCadastrado, Movimentacao, SaidaMultipla, PrevisaoConsumo: dataclasses representando as entidades.

    Database: gerencia conexão SQLite, criação de tabelas, backups, importação.

    SistemaAlmoxarifado: contém toda a lógica de negócio (cadastrar, buscar, movimentar, prever, etc.).

    JanelaPrincipal: classe principal da interface, herda de QMainWindow.

    CampoAutocomplete: QLineEdit personalizado com QCompleter para sugestões.

    ClickableLabel e DoubleClickLabel: labels que emitem sinais de clique e duplo clique.

Banco de Dados

    Conexão via sqlite3 com row_factory = sqlite3.Row.

    Consultas com placeholders para evitar SQL injection.

    Transações utilizadas em operações que envolvem múltiplas escritas.

Imagens

    Função comprimir_imagem(): usa PIL para redimensionar e salvar em JPEG; fallback para leitura binária.

    bytes_para_qpixmap(): converte bytes em QPixmap e escala para as dimensões desejadas.

    mostrar_foto_grande(): exibe foto em diálogo centralizado.

Timezone

    O banco armazena timestamps em UTC (padrão SQLite com CURRENT_TIMESTAMP).

    A função utc_to_local_brasil() converte para o horário de São Paulo usando zoneinfo (Python 3.9+) ou pytz.

    Isso garante que as datas exibidas no histórico estejam no fuso correto.

Previsão de Consumo

    Utiliza os últimos 90 dias de saídas (configurável futuramente).

    Filtra valores acima de limite_valor_absurdo (definido nas configurações) para evitar distorções.

    Calcula consumo diário médio e desvio padrão.

    Dias restantes = (estoque_atual - estoque_minimo) / consumo_diario (se consumo > 0).

Personalização e Configurações
Configurações via Interface

    Acessíveis pelo menu Ajuda → Configurações.

    Limite de valor absurdo: valores diários acima deste limite são ignorados no cálculo de consumo.

    Período de previsão: define quantos dias à frente a previsão é calculada (afeta o campo "Previsão" no relatório).

    Temas: seleção e aplicação imediata.

Configurações via Banco

A tabela configuracoes armazena pares chave/valor. Alguns são atualizados automaticamente (ex: total_itens). O sistema lê esses valores para personalizar comportamentos.
QSettings

    Usado para persistir o tema e outras preferências do usuário (não compartilhadas entre usuários do sistema).

Possíveis Melhorias

    Relatórios gráficos: implementar gráficos de consumo na aba Previsão (usando matplotlib ou PyQtChart).

    Múltiplos almoxarifados: suporte a diferentes depósitos.

    Controle de usuários e permissões: login e níveis de acesso.

    Exportação para PDF com layout profissional (usando ReportLab ou WeasyPrint).

    Notificações por email quando estoque crítico for atingido.

    Scanner de código de barras para agilizar entrada/saída.

    Sincronização com servidor remoto (via API) para ambientes com múltiplos pontos de acesso.

Conclusão

O Sistema de Almoxarifado é uma ferramenta completa e moderna para gestão de estoque, com foco em usabilidade e recursos visuais. Sua arquitetura modular e documentação clara facilitam a manutenção e a expansão. A integração com dashboard externo permite a criação de painéis de monitoramento em tempo real, elevando o nível de controle e análise.

Versão da Documentação: 2.0 (alinhada com o código v2.7.4)
Data: 19/03/2026