# Some shared hosts can't compile mysqlclient; fall back to pure-Python PyMySQL if present.
try:
    import MySQLdb  # noqa: F401
except ImportError:
    try:
        import pymysql

        pymysql.version_info = (2, 2, 7, "final", 0)
        pymysql.install_as_MySQLdb()
    except ImportError:
        pass
