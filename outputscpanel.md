\[nexopayc@alpha ~\]$ cd ~/nexopay2

\[nexopayc@alpha nexopay2\]$ ^C

\[nexopayc@alpha nexopay2\]$ cd ~

echo "===== 1. HOME ====="; pwd; ls -la ~ | head -40

echo "===== 2. DOMAINS & FOLDERS ====="

uapi --output=jsonpretty DomainInfo domains\_data 2>/dev/null | grep -E '"(domain|documentroot|type|servername)"'

echo "===== 3. PYTHON APPS (secrets hidden) ====="

cloudlinux-selector get --json --interpreter=python 2>/dev/null | python3 -c '

import sys, json

d = json.load(sys.stdin)

for user in d.get("users", {}).values():

for root, app in user.get("applications", {}).items():

app.pop("env\_vars", None)

print(root, "->", app)'

echo "===== 4. PYTHON VERSIONS AVAILABLE ====="; ls -d /opt/alt/python3\*/ 2>/dev/null

echo "===== 5. DATABASE SERVER ====="; uapi --output=jsonpretty Mysql get\_server\_information 2>/dev/null | grep -E '"(version|type)"'

uapi --output=jsonpretty Mysql list\_databases 2>/dev/null | grep -E '"database"'

echo "===== 6. TOOLS ====="; git --version; command -v flock mysqldump mariadb-dump python3 || true

echo "===== 7. DISK ====="; uapi --output=jsonpretty Quota get\_quota\_info 2>/dev/null | grep -E 'megabyte|inode' | head -8

echo "===== 8. NEXOPAY2 (old app) ====="; ls -la ~/nexopay2 | head -30

head -20 ~/nexopay2/passenger\_wsgi.py 2>/dev/null

git -C ~/nexopay2 remote -v 2>/dev/null | sed -E 's#://\[^@/\]+@#://\*\*\*@#'

git -C ~/nexopay2 log --oneline -3 2>/dev/null

echo "===== 9. public\_html (secrets hidden) ====="; ls -la ~/public\_html | head -30

grep -viE 'setenv|password|secret|key' ~/public\_html/.htaccess 2>/dev/null

grep -iE '^\\s\*setenv' ~/public\_html/.htaccess 2>/dev/null | awk '{print $1, $2, "= \*\*\*"}'

echo "===== DONE =====" ConnectTimeout=8 -o StrictHostKeyChecking=accept-new -T -p 443 git@ssh.github.com 2>&1 | head -2

\===== 1. HOME =====

/home/nexopayc

total 80

drwx--x--x 27 nexopayc nexopayc 4096 Jun 27 22:48 .

drwxr-xr-x 3 root root 22 May 22 05:35 ..

\-rw------- 1 nexopayc nexopayc 25076 Aug 11 11:20 .bash\_history

\-rw-r--r-- 1 nexopayc nexopayc 18 Apr 25 00:10 .bash\_logout

\-rw-r--r-- 1 nexopayc nexopayc 141 Apr 25 00:10 .bash\_profile

\-rw-r--r-- 1 nexopayc nexopayc 492 Apr 25 00:10 .bashrc

drwxrwx--x 5 nexopayc nexopayc 39 May 22 05:35 .cagefs

drwx------ 3 nexopayc nexopayc 22 Apr 25 00:10 .caldav

drwxr-xr-x 2 nexopayc nexopayc 48 May 12 03:18 .cl.selector

drwx------ 2 nexopayc nexopayc 22 Apr 25 00:11 .clwpos

drwxr-xr-x 3 nexopayc nexopayc 36 Jun 5 07:37 .composer

drwx------ 8 nexopayc nexopayc 178 Sep 27 12:29 .cpanel

drwxr-xr-x 2 nexopayc nexopayc 6 Apr 25 00:10 .htpasswds

\-rw-r--r-- 1 nexopayc nexopayc 106 Apr 25 02:50 .imunify\_patch\_id

drwxr-xr-x 2 nexopayc nexopayc 6 Apr 25 10:39 .koality

\-rw------- 1 nexopayc nexopayc 591 Sep 27 08:47 .lastlogin

\-rw-r--r-- 1 nexopayc nexopayc 102 Apr 25 02:50 .myimunify\_id

drwxr-xr-x 2 nexopayc nexopayc 4096 Sep 23 13:18 .razor

drwx--x--x 5 nexopayc nexopayc 78 Apr 25 10:39 .softaculous

drwx------ 2 nexopayc nexopayc 60 Sep 5 12:28 .spamassassin

\-rw-r--r-- 1 nexopayc nexopayc 0 Apr 25 00:10 .spamassassinboxenable

\-rw-r--r-- 1 nexopayc nexopayc 0 Apr 25 00:10 .spamassassinenable

drwx------ 2 nexopayc nexopayc 157 Jun 5 00:48 .ssh

drwx------ 2 nexopayc nexopayc 28 May 1 03:22 .subaccounts

drwx------ 2 nexopayc nexopayc 6 Apr 25 10:39 .trash

\-rw------- 1 nexopayc nexopayc 684 May 12 03:18 .wp-toolkit-identifier

lrwxrwxrwx 1 nexopayc nexopayc 34 Apr 25 00:17 access-logs -> /etc/apache2/logs/domlogs/nexopayc

drwxr-x--- 3 nexopayc mail 44 Sep 27 02:27 etc

drwx------ 2 nexopayc nexopayc 188 Sep 26 18:00 logs

drwxrws--- 2 nobody nexopayc 6 May 12 03:18 lscache

drwxr-x--x 13 nexopayc nexopayc 4096 Sep 23 13:18 mail

drwxr-xr-x 13 nexopayc nexopayc 4096 Jun 19 00:06 nexopay2

drwxr-xr-x 13 nexopayc nexopayc 4096 Jun 19 12:32 nexorah2

drwxr-xr-x 3 nexopayc nexopayc 22 Apr 25 00:10 public\_ftp

drwxr-xr-x 6 nexopayc nexopayc 168 Sep 24 04:51 public\_html

drwx------ 3 nexopayc nexopayc 22 Jun 4 19:48 repositories

drwxr-xr-x 5 nexopayc nexopayc 77 Aug 31 01:01 ssl

drwxr-xr-x 7 nexopayc nexopayc 4096 Jun 6 19:09 tmp

lrwxrwxrwx 1 nexopayc nexopayc 11 Apr 25 00:10 www -> public\_html

\===== 2. DOMAINS & FOLDERS =====

"documentroot" : "/home/nexopayc/nexorah2/public",

"domain" : "nexorah.com.bd",

"servername" : "nexorah.com.bd.nexopay.com.bd",

"type" : "addon\_domain",

"documentroot" : "/home/nexopayc/public\_html",

"domain" : "nexopay.com.bd",

"servername" : "nexopay.com.bd",

"type" : "main\_domain",

\===== 3. PYTHON APPS (secrets hidden) =====

jailshell: python3: command not found

\===== 4. PYTHON VERSIONS AVAILABLE =====

/opt/alt/python311/ /opt/alt/python35/

\===== 5. DATABASE SERVER =====

"version" : "10.11.18-MariaDB"

"database" : "nexopayc\_db\_nexopay2",

"database" : "nexopayc\_db\_nexorah2",

\===== 6. TOOLS =====

git version 2.48.2

/usr/bin/flock

/usr/bin/mysqldump

/usr/bin/mariadb-dump

\===== 7. DISK =====

"inode\_limit" : "0",

"inodes\_remain" : "0",

"inodes\_used" : "0",

"megabyte\_limit" : 2048,

"megabytes\_remain" : 2048,

"megabytes\_used" : "0.00",

"under\_inode\_limit" : "1",

"under\_megabyte\_limit" : "1",

\===== 8. NEXOPAY2 (old app) =====

total 5916

drwxr-xr-x 13 nexopayc nexopayc 4096 Jun 19 00:06 .

drwx--x--x 27 nexopayc nexopayc 4096 Jun 27 22:48 ..

\-rw-r--r-- 1 nexopayc nexopayc 252 Jun 5 00:56 .editorconfig

\-rw-r--r-- 1 nexopayc nexopayc 1206 Jun 7 13:11 .env

\-rw-r--r-- 1 nexopayc nexopayc 1086 Jun 5 00:56 .env.example

drwx------ 7 nexopayc nexopayc 4096 Aug 11 21:33 .git

\-rw-r--r-- 1 nexopayc nexopayc 186 Jun 5 00:56 .gitattributes

\-rw-r--r-- 1 nexopayc nexopayc 283 Jun 5 00:56 .gitignore

\-rw-r--r-- 1 nexopayc nexopayc 1884 Jun 5 00:56 CPANEL\_DEPLOYMENT\_GUIDE.md

\-rw-r--r-- 1 nexopayc nexopayc 3911 Jun 5 00:56 README.md

drwxr-xr-x 7 nexopayc nexopayc 78 Jun 18 23:43 app

\-rw-r--r-- 1 nexopayc nexopayc 425 Jun 5 00:56 artisan

drwxr-xr-x 3 nexopayc nexopayc 55 Jun 19 12:49 bootstrap

\-rw-r--r-- 1 nexopayc nexopayc 53 Jun 5 00:56 composer.bat

\-rw-r--r-- 1 nexopayc nexopayc 3171 Jun 7 13:10 composer.json

\-rw-r--r-- 1 nexopayc nexopayc 336696 Jun 7 13:10 composer.lock

\-rw-r--r-- 1 nexopayc nexopayc 3561371 Jun 5 00:56 composer.phar

drwxr-xr-x 2 nexopayc nexopayc 188 Jun 5 00:56 config

drwxr-xr-x 5 nexopayc nexopayc 74 Jun 5 00:56 database

\-rw-r--r-- 1 nexopayc nexopayc 329 Jun 7 13:04 error\_log

\-rw-r--r-- 1 nexopayc nexopayc 223 Jun 5 00:56 jsconfig.json

\-rw-r--r-- 1 nexopayc nexopayc 41411 Jun 6 00:45 live.html

\-rw-r--r-- 1 nexopayc nexopayc 200038 Jun 19 00:06 package-lock.json

\-rw-r--r-- 1 nexopayc nexopayc 1106 Jun 19 00:06 package.json

\-rw-r--r-- 1 nexopayc nexopayc 1322 Jun 5 00:56 phpunit.xml

\-rw-r--r-- 1 nexopayc nexopayc 93 Jun 5 00:56 postcss.config.js

drwxr-xr-x 4 nexopayc nexopayc 117 Jun 5 07:39 public

drwxr-xr-x 5 nexopayc nexopayc 40 Jun 5 00:56 resources

drwxr-xr-x 2 nexopayc nexopayc 56 Aug 2 21:38 routes

origin git@github.com:irrepressible007/nexopay2.git (fetch)

origin git@github.com:irrepressible007/nexopay2.git (push)

e9065ed (HEAD -> main, origin/main, origin/HEAD) Enlarge event logo on 2in x 5in print ticket and optimize text spacing

9997024 Allow full participant name and details to wrap on 2in x 5in print ticket without truncation

99a9ac7 Fix ticket print page overflow with React portal and exact 2in x 5in page size

\===== 9. public\_html (secrets hidden) =====

total 32

drwxr-xr-x 6 nexopayc nexopayc 168 Sep 24 04:51 .

drwx--x--x 27 nexopayc nexopayc 4096 Sep 27 12:34 ..

\-rw-r--r-- 1 nexopayc nexopayc 1020 Sep 24 04:51 .htaccess

drwxr-xr-x 3 nexopayc nexopayc 28 Aug 5 03:58 .well-known

drwxr-xr-x 3 nexopayc nexopayc 41 Aug 11 21:33 build

drwxr-xr-x 2 nexopayc nexopayc 6 Jul 22 09:49 cgi-bin

\-rw-r--r-- 1 nexopayc nexopayc 13439 Jun 5 23:52 error\_log

\-rw-r--r-- 1 nexopayc nexopayc 0 Jun 5 00:56 favicon.ico

\-rw-r--r-- 1 nexopayc nexopayc 570 Jun 5 23:53 index.php

drwxr-xr-x 2 nexopayc nexopayc 64 Jun 7 05:59 logo

\-rw-r--r-- 1 nexopayc nexopayc 24 Jun 5 00:56 robots.txt

lrwxrwxrwx 1 nexopayc nexopayc 42 Jun 5 07:39 storage -> /home/nexopayc/nexopay2/storage/app/public

Options -MultiViews -Indexes

RewriteEngine On

\# Handle Authorization Header

RewriteCond %{HTTP:Authorization} .

RewriteRule .\* - \[E=HTTP\_AUTHORIZATION:%{HTTP:Authorization}\]

\# Handle X-XSRF-Token Header

RewriteCond %{HTTP:x-xsrf-token} .

RewriteRule .\* - \[E=HTTP\_X\_XSRF\_TOKEN:%{HTTP:X-XSRF-Token}\]

\# Redirect Trailing Slashes If Not A Folder...

RewriteCond %{REQUEST\_FILENAME} !-d

RewriteCond %{REQUEST\_URI} (.+)/$

RewriteRule ^ %1 \[L,R=301\]

\# Send Requests To Front Controller...

RewriteCond %{REQUEST\_FILENAME} !-d

RewriteCond %{REQUEST\_FILENAME} !-f

RewriteRule ^ index.php \[L\]

\# php -- BEGIN cPanel-generated handler, do not edit

\# Set the “ea-php82” package as the default “PHP” programming language.

AddHandler application/x-httpd-ea-php82 .php .php8 .phtml

\# php -- END cPanel-generated handler, do not edit

\===== 10. CRON JOBS =====

sed: -e expression #1, char 15: unterminated \`s' command

\===== 11. GITHUB REACHABLE? =====

fatal: could not read Username for 'https://github.com': terminal prompts disabled

Warning: Permanently added '\[ssh.github.com\]:443' (ED25519) to the list of known hosts.

Hi irrepressible007! You've successfully authenticated, but GitHub does not provide shell access.

\===== DONE =====

\[nexopayc@alpha ~\]$