async def init_product_name_schema(conn):
    await conn.execute("""
        CREATE OR REPLACE FUNCTION supplierhub_product_title(
            input_name TEXT,
            input_sku TEXT
        )
        RETURNS TEXT
        LANGUAGE plpgsql
        IMMUTABLE
        AS $$
        DECLARE
            title TEXT := BTRIM(COALESCE(input_name, ''));
            sku TEXT := BTRIM(COALESCE(input_sku, ''));
        BEGIN
            IF sku = '' THEN
                RETURN title;
            END IF;

            LOOP
                IF LOWER(title) = LOWER(sku) THEN
                    title := '';
                ELSIF LOWER(RIGHT(title, LENGTH(sku) + 1))
                      = LOWER(' ' || sku) THEN
                    title := BTRIM(
                        LEFT(title, LENGTH(title) - LENGTH(sku) - 1)
                    );
                ELSE
                    EXIT;
                END IF;
            END LOOP;

            IF title = '' THEN
                RETURN sku;
            END IF;

            RETURN title || ' ' || sku;
        END;
        $$;

        CREATE OR REPLACE FUNCTION supplierhub_format_product_title()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $$
        BEGIN
            NEW.product_name := supplierhub_product_title(
                NEW.product_name,
                NEW.supplier_sku
            );
            RETURN NEW;
        END;
        $$;

        DROP TRIGGER IF EXISTS supplierhub_product_title_trigger
        ON products;

        CREATE TRIGGER supplierhub_product_title_trigger
        BEFORE INSERT OR UPDATE OF product_name, supplier_sku
        ON products
        FOR EACH ROW
        EXECUTE FUNCTION supplierhub_format_product_title();

        UPDATE products
        SET product_name = supplierhub_product_title(
            product_name,
            supplier_sku
        )
        WHERE product_name IS DISTINCT FROM supplierhub_product_title(
            product_name,
            supplier_sku
        );
    """)