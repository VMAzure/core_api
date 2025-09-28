-- Name: az_image; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.az_image (
    id integer NOT NULL,
    codice_modello character varying(50) NOT NULL,
    marca_alias character varying(255),
    modello_alias character varying(255),
    model_variant character varying(50),
    ultima_modifica timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.az_image OWNER TO postgres;

--
-- Name: az_image_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.az_image_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.az_image_id_seq OWNER TO postgres;

--
-- Name: az_image_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.az_image_id_seq OWNED BY public.az_image.id;
