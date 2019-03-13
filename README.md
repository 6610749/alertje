# debijenkorf web scraper

## Installation

Installation requires Python 3.6+. It is recommended to use virtualenv.

### Installing virtualenv

    pip install virtualenvwrapper
    export WORKON_HOME=/opt/Envs
    mkdir -p $WORKON_HOME
    source /usr/local/bin/virtualenvwrapper.sh
    mkvirtualenv debijenkorf --python=python3.6

To have virtualenv available next time you login:

    echo 'WORKON_HOME=$HOME/Envs' >> ~/.bashrc
    echo 'source /usr/local/bin/virtualenvwrapper.sh' >> ~/.bashrc

### Installing dependencies

    mkdir -p /opt/debijenkorf
    cp debijenkorf.zip /opt/debijenkorf
    cd /opt/debijenkorf
    unzip debijenkorf.zip
    chown -R www-data:www-data /opt/debijenkorf /opt/Envs/debijenkorf
    workon debijenkorf
    pip install -r requirements.txt

### Installing MySQL database

    cat conf/create.sql | mysql -uroot
    python manage.py migrate

### Installing for Apache

    sudo apt-get install apache2 libapache2-mod-wsgi-py3
    ln -s /opt/debijenkorf/conf/client.alertje.nl.conf /etc/apache2/sites-enabled/
    a2enmod wsgi
    systemctl restart apache2

### Migrating data

    python manage.py populate

### Installing on supervisord

    ln -s /opt/debijenkorf/conf/debijenkorf_supervisord.conf /etc/supervisor/conf.d/
    supervisorctl reread
    supervisorctl update

## Running

To manually run the components:

### Scrapper (CLI)

Running the software is done in the terminal using:

    python main.py

### SMS sender (CLI)

Running the software is done in the terminal using:

    python main.py --sms-messenger

### Web server (Flask)

Running the software is done in the terminal using:

    python main.py --server