# Called from the first interactive local-console login after Debian setup.
case $- in
    *i*)
        if [ -t 0 ] && [ -t 1 ] && [ "$(tty 2>/dev/null)" = /dev/tty1 ] &&
           [ -x /usr/local/sbin/cyberdeck-firstboot-install ]; then
            /usr/local/sbin/cyberdeck-firstboot-install || true
        fi
        ;;
esac
