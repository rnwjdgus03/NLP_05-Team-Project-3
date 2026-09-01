from kosis_postgres_store import PostgresKosisMetadataStore


def main() -> None:
    with PostgresKosisMetadataStore("postgresql:///kosis_project") as store:
        for terms in (["농산물"], ["석탄", "석유제품"], ["생산자물가", "농산물"]):
            rows = store.item_table_recall(terms, limit=300, prd_se="M", balanced_terms=True)
            print("TERMS", terms, "ROWS", len(rows))
            for row in rows:
                if row["org_id"] == "301" and row["tbl_id"].startswith("DT_404Y"):
                    print("TARGET", row)


if __name__ == "__main__":
    main()
