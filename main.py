"""
Gera regras de associação do tipo *“quem assiste A e B também assiste C”* a partir
de um histórico de visualização de usuários ou, caso não exista, cria um dataset
sintético com base nos gêneros do catálogo Netflix.

― Uso básico ―
$ python apriori_streaming.py --catalog netflix_titles.csv
  (gera dados sintéticos, extrai regras, produz gráficos PNG e salva CSV)

― Opções principais ―
  --watch_history  Caminho (CSV) com colunas user_id,title (opcional)
  --min_support    Suporte mínimo (fração), default 0.01
  --min_conf       Confiança mínima, default 0.20
  --top_n          Nº de regras no output, default 20
  --seed           Seed para reprodutibilidade, default 42
  --out_rules      Nome do CSV de saída, default rules.csv
  --no_plots       Não gera gráficos quando usado
"""
import argparse, os, random, itertools, sys
from collections import defaultdict
import pandas as pd
import matplotlib.pyplot as plt

try:
    import networkx as nx
except ImportError:
    nx = None  # gráfico de rede é opcional

def load_catalog(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        sys.exit(f'Catálogo não encontrado: {path}')
    df = pd.read_csv(path)
    if not {'title', 'listed_in'}.issubset(df.columns):
        sys.exit('Catálogo precisa conter colunas "title" e "listed_in".')
    df = df[['title', 'listed_in']].dropna()
    df['genres'] = df['listed_in'].str.split(', ')
    return df

def generate_synthetic_watch(df_catalog: pd.DataFrame,
                             n_users: int = 1000,
                             seed: int = 42) -> list[list[str]]:
    """Cria transações fictícias a partir dos gêneros do catálogo."""
    random.seed(seed)
    genre_to_titles = defaultdict(list)
    for _, row in df_catalog.iterrows():
        for g in row['genres']:
            genre_to_titles[g].append(row['title'])
    genres = list(genre_to_titles.keys())

    transactions = []
    for _ in range(n_users):
        chosen_genres = random.sample(genres, random.randint(1, 3))
        watched = set()
        for g in chosen_genres:
            titles = genre_to_titles[g]
            watched.update(random.sample(titles,
                                         min(len(titles),
                                             random.randint(3, 10))))
        transactions.append(list(watched))
    return transactions

def load_watch_history(path: str) -> list[list[str]]:
    """Converte arquivo user_id,title em lista de transações."""
    df = pd.read_csv(path)
    if not {'user_id', 'title'}.issubset(df.columns):
        sys.exit('watch_history precisa ter colunas "user_id" e "title".')
    return df.groupby('user_id')['title'].apply(set).tolist()

def mine_rules(transactions: list[list[str]],
               min_support: float = 0.01,
               min_conf: float = 0.2,
               top_n: int = 20) -> pd.DataFrame:
    """Extrai regras (A→B) com contagem dupla e devolve DataFrame."""
    n_trans = len(transactions)

    item_cnt = defaultdict(int)
    for t in transactions:
        for i in t:
            item_cnt[i] += 1
    item_sup = {i: c / n_trans for i, c in item_cnt.items()
                if c / n_trans >= min_support}
    freq_items = set(item_sup)

    pair_cnt = defaultdict(int)
    for t in transactions:
        freq_in_t = [i for i in t if i in freq_items]
        for a, b in itertools.combinations(freq_in_t, 2):
            pair_cnt[tuple(sorted((a, b)))] += 1
    pair_sup = {p: c / n_trans for p, c in pair_cnt.items()
                if c / n_trans >= min_support}

    rules = []
    for (a, b), supp in pair_sup.items():
        supp_a, supp_b = item_sup[a], item_sup[b]

        conf_ab = supp / supp_a
        if conf_ab >= min_conf:
            lift_ab = conf_ab / supp_b
            rules.append((a, b, supp, conf_ab, lift_ab))

        conf_ba = supp / supp_b
        if conf_ba >= min_conf:
            lift_ba = conf_ba / supp_a
            rules.append((b, a, supp, conf_ba, lift_ba))

    df_rules = pd.DataFrame(rules,
                            columns=['antecedent', 'consequent',
                                     'support', 'confidence', 'lift'])
    return df_rules.sort_values('lift', ascending=False).head(top_n)

def plot_bar(df_rules: pd.DataFrame, outfile: str):
    plt.figure(figsize=(10, 5))
    plt.bar(range(len(df_rules)), df_rules['lift'])
    plt.xticks(range(len(df_rules)),
               [f"{a}→{c}" for a, c in
                zip(df_rules['antecedent'], df_rules['consequent'])],
               rotation=90)
    plt.ylabel('Lift')
    plt.title('Top Rules by Lift')
    plt.tight_layout()
    plt.savefig(outfile, dpi=300)
    plt.close()

def plot_network(df_rules: pd.DataFrame, outfile: str):
    if nx is None:
        print('networkx não instalado – pulando o grafo.')
        return
    G = nx.DiGraph()
    for _, r in df_rules.iterrows():
        G.add_edge(r['antecedent'], r['consequent'],
                   weight=f"{r['confidence']:.2f}")
    plt.figure(figsize=(8, 6))
    pos = nx.spring_layout(G, k=0.6, seed=42)
    nx.draw(G, pos, with_labels=True, node_size=900, font_size=7)
    nx.draw_networkx_edge_labels(G, pos,
                                 edge_labels=nx.get_edge_attributes(G,
                                                                    'weight'),
                                 font_size=6)
    plt.title('Association Network (confidence)')
    plt.axis('off')
    plt.tight_layout()
    plt.savefig(outfile, dpi=300)
    plt.close()

def main():
    ap = argparse.ArgumentParser(description='Apriori para catálogo streaming')
    ap.add_argument('--catalog', required=True,
                    help='CSV com títulos da Netflix (col: title, listed_in)')
    ap.add_argument('--watch_history',
                    help='CSV user_id,title (opcional; se omisso gera sintético)')
    ap.add_argument('--min_support', type=float, default=0.01)
    ap.add_argument('--min_conf', type=float, default=0.2)
    ap.add_argument('--top_n', type=int, default=20)
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--out_rules', default='rules.csv')
    ap.add_argument('--no_plots', action='store_true',
                    help='Não gera PNGs')
    args = ap.parse_args()

    df_catalog = load_catalog(args.catalog)

    if args.watch_history and os.path.exists(args.watch_history):
        transactions = load_watch_history(args.watch_history)
        print(f'Carregado histórico real: {len(transactions)} usuários.')
    else:
        print('Gerando histórico sintético…')
        transactions = generate_synthetic_watch(df_catalog,
                                                n_users=1000,
                                                seed=args.seed)

    rules_df = mine_rules(transactions,
                          min_support=args.min_support,
                          min_conf=args.min_conf,
                          top_n=args.top_n)
    rules_df.to_csv(args.out_rules, index=False)
    print(f'Salvo {len(rules_df)} regras em {args.out_rules}')

    if not args.no_plots:
        plot_bar(rules_df, 'rules_lift.png')
        plot_network(rules_df, 'rules_network.png')
        print('Gráficos gerados: rules_lift.png, rules_network.png')

if __name__ == '__main__':
    main()
